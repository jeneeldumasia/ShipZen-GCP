import base64
import os
import time
import requests
import jwt
import logging

logger = logging.getLogger(__name__)


def get_github_app_token(repo_url: str, write: bool = False) -> str:
    """Mint a GitHub App installation token for exactly one repository.

    The token is limited to that repository and to `contents: read` (or
    `contents: write` when write=True, which only the controller needs, to
    commit to the tenants repo). Without these limits a token minted to clone
    one repo could read and push to every repo in the installation.
    """
    GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
    GITHUB_APP_PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY")

    if not GITHUB_APP_ID or not GITHUB_APP_PRIVATE_KEY or not repo_url.startswith("https://github.com/"):
        return None
    try:
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + (10 * 60), "iss": GITHUB_APP_ID}
        pk = GITHUB_APP_PRIVATE_KEY.replace("\\n", "\n")
        encoded_jwt = jwt.encode(payload, pk, algorithm="RS256")
        headers = {"Authorization": f"Bearer {encoded_jwt}", "Accept": "application/vnd.github.v3+json"}
        resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/installation", headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        installation_id = resp.json()["id"]
        token_resp = requests.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers=headers, timeout=10,
            json={"repositories": [repo],
                  "permissions": {"contents": "write" if write else "read"}})
        if token_resp.status_code != 201:
            logger.error(f"GitHub refused an installation token for {owner}/{repo}: HTTP {token_resp.status_code}")
            return None
        return token_resp.json()["token"]
    except Exception as e:
        logger.error(f"Error fetching GitHub App token: {type(e).__name__}")
        return None


def git_auth_header(token: str) -> str:
    """The http.extraHeader value that authenticates git to GitHub with an installation token."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"AUTHORIZATION: basic {basic}"


def git_auth_env(token: str) -> dict:
    """Environment variables that make `git` send the token as a header.

    Passing it through GIT_CONFIG_* (git >= 2.31) keeps the token out of the
    clone URL, out of the command line (and so out of exception messages), and
    out of the cloned repository's .git/config.
    """
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": git_auth_header(token),
        "GIT_TERMINAL_PROMPT": "0",
    }
