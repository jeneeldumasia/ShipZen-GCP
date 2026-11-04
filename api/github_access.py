"""Check that the signed-in user can read a GitHub repository (security finding C3).

The worker clones private repositories with a ShipZen GitHub App token, and the
App can read every repository where anyone installed it. So before a project
or deployment may name a repository, the API asks GitHub, *with the user's own
token*, whether this user can see it. Without this, any ShipZen user could
build (and so read) another user's private code.

Each project is bound to the first repository it uses (projects.github_repo_id);
later deployments and push webhooks must match it.
"""
import logging
import os
import re
from typing import Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger('api')

_GITHUB_REPO_RE = re.compile(r"\Ahttps://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?\Z")


def parse_github_repo(repo_url: str) -> Optional[tuple]:
    """(owner, repo) for a https://github.com/owner/repo[.git] URL, else None."""
    m = _GITHUB_REPO_RE.match(repo_url or "")
    return (m.group(1), m.group(2)) if m else None


def check_repo_access(user, repo_url: str) -> Optional[dict]:
    """Confirm `user` can read `repo_url` on GitHub.

    Returns {"id", "full_name", "private"} for github.com repositories, or None
    for other hosts (those are cloned anonymously, so only public code can be
    built from them). Raises HTTPException when GitHub says no, or can't be asked.
    """
    parsed = parse_github_repo(repo_url)
    if not parsed:
        return None
    token = getattr(user, "github_token", None)
    if not token:
        # Only the local-development stub sign-in has no GitHub token.
        if os.getenv("ENABLE_LOCAL_STUB_AUTH", "false").lower() == "true" \
                and os.getenv("ENVIRONMENT", "development") != "production":
            return None
        raise HTTPException(status_code=403, detail="Can't verify your access to that GitHub repository; sign in again.")

    owner, repo = parsed
    try:
        resp = httpx.get(f"https://api.github.com/repos/{owner}/{repo}",
                         headers={"Authorization": f"Bearer {token}",
                                  "Accept": "application/vnd.github+json"},
                         timeout=10)
    except httpx.HTTPError as e:
        logger.warning(f"GitHub repository check failed: {type(e).__name__}")
        raise HTTPException(status_code=503, detail="Couldn't reach GitHub to check repository access; try again.")

    if resp.status_code == 200:
        data = resp.json()
        return {"id": data["id"], "full_name": data["full_name"], "private": bool(data.get("private"))}
    if resp.status_code in (403, 404):
        raise HTTPException(
            status_code=403,
            detail=(f"You don't have access to {owner}/{repo} on GitHub, or it doesn't exist. "
                    "For a private repository, install the ShipZen GitHub App on it."))
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="GitHub token is invalid or expired. Sign in again.")
    raise HTTPException(status_code=503, detail=f"GitHub returned {resp.status_code} while checking repository access; try again.")


def enforce_project_binding(project: dict, repo: Optional[dict]) -> None:
    """403 if the project is bound to a different repository than `repo`."""
    bound = project.get("github_repo_id")
    if repo and bound and int(bound) != int(repo["id"]):
        raise HTTPException(
            status_code=403,
            detail=(f"This project deploys {project.get('github_repo_full_name')}. "
                    "Create a new project to deploy a different repository."))


# ── Reading repositories through the GitHub API (security finding H3) ────────
# The API used to run `git ls-remote` / `git clone` on any URL a user typed,
# from inside the API pod, which can reach internal addresses. Now it only talks
# to api.github.com, with the user's own token, so private repositories they
# can read work too, and nothing else is reachable.

MAX_BRANCHES = 300
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024   # compressed download
MAX_SNAPSHOT_FILES = 20_000
MAX_SNAPSHOT_UNPACKED = 300 * 1024 * 1024


def _github_headers(user) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = getattr(user, "github_token", None)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _require_github(repo_url: str) -> tuple:
    parsed = parse_github_repo(repo_url)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="Only github.com repositories can be read automatically; type the branch name instead.")
    return parsed


def _not_found(owner: str, repo: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=(f"{owner}/{repo} was not found, or you have no access to it. For a private "
                "repository, install the ShipZen GitHub App on it."))


def list_branches(user, repo_url: str) -> list:
    """Branch names (first MAX_BRANCHES) of a github.com repository the user can read."""
    owner, repo = _require_github(repo_url)
    branches, page = [], 1
    while len(branches) < MAX_BRANCHES:
        try:
            resp = httpx.get(f"https://api.github.com/repos/{owner}/{repo}/branches",
                             headers=_github_headers(user), params={"per_page": 100, "page": page},
                             timeout=15)
        except httpx.HTTPError as e:
            logger.warning(f"GitHub branch listing failed: {type(e).__name__}")
            raise HTTPException(status_code=503, detail="Couldn't reach GitHub; try again.")
        if resp.status_code in (403, 404):
            raise _not_found(owner, repo)
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="GitHub token is invalid or expired. Sign in again.")
        if resp.status_code != 200:
            raise HTTPException(status_code=503, detail=f"GitHub returned {resp.status_code}; try again.")
        batch = [b["name"] for b in resp.json()]
        branches.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return branches[:MAX_BRANCHES]


def download_snapshot(user, repo_url: str, branch: str, dest: str) -> None:
    """Unpack the files of `branch` into `dest`, from GitHub's tarball endpoint.

    Size-capped, and safe against archive tricks: only regular files and
    directories, no absolute paths, no '..', no links or devices.
    """
    import io
    import os
    import tarfile

    owner, repo = _require_github(repo_url)
    buf = io.BytesIO()
    try:
        with httpx.stream("GET", f"https://api.github.com/repos/{owner}/{repo}/tarball/{branch}",
                          headers=_github_headers(user), timeout=60, follow_redirects=True) as resp:
            if resp.status_code in (403, 404):
                raise _not_found(owner, repo)
            if resp.status_code != 200:
                raise HTTPException(status_code=503, detail=f"GitHub returned {resp.status_code}; try again.")
            for chunk in resp.iter_bytes():
                buf.write(chunk)
                if buf.tell() > MAX_SNAPSHOT_BYTES:
                    raise HTTPException(status_code=413, detail="Repository is too large to analyse (over 100 MB).")
    except httpx.HTTPError as e:
        logger.warning(f"GitHub tarball download failed: {type(e).__name__}")
        raise HTTPException(status_code=503, detail="Couldn't download the repository from GitHub; try again.")

    buf.seek(0)
    root = os.path.realpath(dest)
    files = unpacked = 0
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        for member in tar:
            # GitHub prefixes every path with "<owner>-<repo>-<sha>/"; drop it.
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            rel = parts[1]
            if ".." in rel.split("/"):
                continue
            target = os.path.realpath(os.path.join(root, rel))
            if not target.startswith(root + os.sep):
                continue
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            if not member.isreg():
                continue  # symlinks, hardlinks, devices: skipped
            files += 1
            unpacked += member.size
            if files > MAX_SNAPSHOT_FILES or unpacked > MAX_SNAPSHOT_UNPACKED:
                raise HTTPException(status_code=413, detail="Repository is too large to analyse.")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            with open(target, "wb") as out:
                out.write(src.read())
