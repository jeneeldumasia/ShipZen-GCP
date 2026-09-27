import os
import time
import requests
import jwt
import logging

logger = logging.getLogger(__name__)

def get_github_app_token(repo_url: str) -> str:
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
        if resp.status_code != 200: return None
        installation_id = resp.json()["id"]
        token_resp = requests.post(f"https://api.github.com/app/installations/{installation_id}/access_tokens", headers=headers, timeout=10)
        if token_resp.status_code != 201: return None
        return token_resp.json()["token"]
    except Exception as e:
        logger.error(f"Error fetching GitHub App token: {e}")
        return None
