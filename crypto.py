"""Encryption at rest: AES-256-GCM with a single master key.

Threat model: this protects data that is stolen "at rest" - a lifted
database backup, a stolen disk/volume, a cloud storage breach where someone
gets read access to the Postgres files or a pg_dump without the app's
environment. It does NOT protect against someone who compromises the running
app itself (they can just ask the app to decrypt, same as the app does for
every request) - that's a different problem (input validation, dependency
hygiene, container isolation, etc).

The master key lives only in the environment (TIMEPILOT_MASTER_KEY, a Docker
secret in production) and is never stored alongside the ciphertext.
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

_NONCE_LEN = 12  # 96-bit nonce, standard for GCM


def generate_key() -> str:
    """Generate a fresh base64-encoded 256-bit key (for `python -m crypto`)."""
    return base64.b64encode(os.urandom(32)).decode()


class Encryptor:
    def __init__(self, b64_key: str):
        if not b64_key:
            raise RuntimeError(
                "TIMEPILOT_MASTER_KEY is not set. Generate one with:\n"
                "  python -c \"import crypto; print(crypto.generate_key())\"\n"
                "and put it in your .env file (never commit it)."
            )
        try:
            key = base64.b64decode(b64_key, validate=True)
        except Exception as e:
            raise RuntimeError(f"TIMEPILOT_MASTER_KEY is not valid base64: {e}")
        if len(key) != 32:
            raise RuntimeError(
                f"TIMEPILOT_MASTER_KEY must decode to 32 bytes (got {len(key)}). "
                "Generate a fresh one - see crypto.generate_key()."
            )
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        ct = self._aead.encrypt(nonce, plaintext, None)
        return nonce + ct

    def decrypt(self, blob: bytes) -> bytes:
        if len(blob) < _NONCE_LEN:
            raise ValueError("Ciphertext too short - corrupt or not encrypted by us")
        nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
        try:
            return self._aead.decrypt(nonce, ct, None)
        except InvalidTag:
            raise ValueError(
                "Decryption failed (bad tag) - wrong TIMEPILOT_MASTER_KEY, or data "
                "was tampered with / corrupted."
            )


if __name__ == "__main__":
    print(generate_key())
