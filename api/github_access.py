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
