"""Per-project environment variables and secrets.

Both /env and /secrets read and write the same Secret Manager secret,
shipzen-project-<project id>, holding one JSON object of KEY: value. An
ExternalSecret syncs it into the project's pods.
"""
import json
import logging

from platform_clients import GCP_PROJECT, _sm_client

logger = logging.getLogger('api')


def secret_id(project_id: str) -> str:
    return f"shipzen-project-{project_id}"


def is_not_found(error: Exception) -> bool:
    return "NotFound" in str(error)


def ensure_project_secret(project_id: str):
    """Ensure that an empty JSON secret exists in GCP Secret Manager for the project."""
    if not _sm_client or not GCP_PROJECT:
        return
    secret_id = f"shipzen-project-{project_id}"
    parent = f"projects/{GCP_PROJECT}"
    try:
        _sm_client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}},
            }
        )
    except Exception:
        pass  # Secret already exists
    try:
        name = f"{parent}/secrets/{secret_id}/versions/latest"
        _sm_client.access_secret_version(request={"name": name})
    except Exception:
        try:
            _sm_client.add_secret_version(
                request={
                    "parent": f"{parent}/secrets/{secret_id}",
                    "payload": {"data": b"{}"},
                }
            )
            logger.info(f"Initialized Secret Manager secret {secret_id}")
        except Exception as e:
            logger.warning(f"Could not add version for secret {secret_id}: {e}")

def delete_project_secret(project_id: str):
    """Delete the project's secret from GCP Secret Manager."""
    if not _sm_client or not GCP_PROJECT:
        return
    secret_id = f"shipzen-project-{project_id}"
    name = f"projects/{GCP_PROJECT}/secrets/{secret_id}"
    try:
        _sm_client.delete_secret(request={"name": name})
        logger.info(f"Deleted Secret Manager secret {secret_id}")
    except Exception as e:
        logger.warning(f"Could not delete secret {secret_id}: {e}")


def load_env(project_id: str) -> dict:
    """The project's KEY: value pairs. Raises if the secret can't be read
    (use is_not_found() to tell a missing secret from other errors)."""
    name = f"projects/{GCP_PROJECT}/secrets/{secret_id(project_id)}/versions/latest"
    res = _sm_client.access_secret_version(request={"name": name})
    return json.loads(res.payload.data.decode("UTF-8"))


def save_env(project_id: str, values: dict) -> None:
    """Store the project's KEY: value pairs as a new version (creating the secret if needed)."""
    parent = f"projects/{GCP_PROJECT}"
    try:
        _sm_client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id(project_id),
                "secret": {"replication": {"automatic": {}}},
            }
        )
    except Exception:
        pass  # Already exists
    _sm_client.add_secret_version(
        request={
            "parent": f"{parent}/secrets/{secret_id(project_id)}",
            "payload": {"data": json.dumps(values).encode("UTF-8")},
        }
    )
