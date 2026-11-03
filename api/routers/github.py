"""GitHub helpers for the UI."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from auth import User, get_current_user
from ratelimit import limiter
from validation import _REPO_URL_RE

logger = logging.getLogger('api')
router = APIRouter()


# ── GitHub Helpers ──────────────────────────────────────────────────────────────


@router.get("/github/branches", tags=["GitHub"])
@limiter.limit("20/minute")
def get_github_branches(request: Request, repo_url: str, current_user: User = Depends(get_current_user)):
    """Fetch branches for a repository. Requires authentication."""
    if not _REPO_URL_RE.match(repo_url):
        raise HTTPException(status_code=400, detail="Invalid repository URL")

    import subprocess
    try:
        # Timeout of 10s is plenty for ls-remote
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            # Check if it's an auth issue (private repo) or repo not found
            err = result.stderr.lower()
            if "authentication" in err or "could not read username" in err or "terminal prompts disabled" in err:
                raise HTTPException(
                    status_code=403, detail="Repository is private or requires authentication")
            raise HTTPException(
                status_code=404, detail="Repository not found or inaccessible")

        branches = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                ref = parts[1]
                if ref.startswith("refs/heads/"):
                    branches.append(ref[len("refs/heads/"):])

        return {"branches": branches, "total": len(branches)}

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504, detail="Request to repository timed out")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching branches for {repo_url}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch branches")
