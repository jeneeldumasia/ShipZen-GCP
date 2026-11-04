"""GitHub helpers for the UI."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from auth import User, get_current_user
from github_access import list_branches
from ratelimit import limiter
from validation import _REPO_URL_RE

logger = logging.getLogger('api')
router = APIRouter()


# ── GitHub Helpers ──────────────────────────────────────────────────────────────


@router.get("/github/branches", tags=["GitHub"])
@limiter.limit("20/minute")
def get_github_branches(request: Request, repo_url: str, current_user: User = Depends(get_current_user)):
    """Branches of a github.com repository the user can read.

    Through the GitHub API with the user's own token, never `git ls-remote`
    from the API pod (security finding H3), so private repositories work and
    no other host can be reached.
    """
    if not _REPO_URL_RE.match(repo_url):
        raise HTTPException(status_code=400, detail="Invalid repository URL")
    branches = list_branches(current_user, repo_url)
    return {"branches": branches, "total": len(branches)}
