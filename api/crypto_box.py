"""Encrypt values the database stores but must never hold in the clear.

Used for projects.webhook_secret (task 25): the per-project HMAC key GitHub
signs push webhooks with. With it, anyone who reads the database could forge
pushes and trigger deploys.

The key is SHIPZEN_DATA_KEY: a Fernet key (32 random bytes, URL-safe base64),
from the repository secret of the same name via Secret Manager and ESO. Keep it
stable: it's what decrypts values in database backups. Without it, values are
stored as before, and plain values written earlier are always still read.
"""
import logging
import os

logger = logging.getLogger('api')

_PREFIX = "enc:v1:"


def _fernet():
    key = os.environ.get("SHIPZEN_DATA_KEY", "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet
    return Fernet(key.encode())


def encrypt_value(value: str) -> str:
    """Encrypted form of value, or value unchanged when no key is configured."""
    f = _fernet()
    if f is None:
        return value
    return _PREFIX + f.encrypt(value.encode()).decode()


def decrypt_value(stored: str) -> str:
    """Plain value from what encrypt_value stored (plain legacy values pass through)."""
    if not stored or not stored.startswith(_PREFIX):
        return stored
    f = _fernet()
    if f is None:
        raise RuntimeError("SHIPZEN_DATA_KEY is not set, so an encrypted value can't be read")
    return f.decrypt(stored[len(_PREFIX):].encode()).decode()
