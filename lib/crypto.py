"""Algorithm-agnostic encryption abstraction for tenant secret storage.

Key resolution order (shared by all algorithms):
  1. ZSCALER_SECRET_KEY env var
  2. <ZSCALER_DB_PATH parent>/secret.key
  3. ~/.config/zs-config/secret.key  (migrating from legacy paths on first access)
  4. Auto-generate and save (first run only)
"""

import base64
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

_KEY_FILE = Path.home() / ".config" / "zs-config" / "secret.key"
_KEY_FILE_LEGACY = Path.home() / ".config" / "z-config" / "secret.key"
_KEY_FILE_LEGACY2 = Path.home() / ".config" / "zscaler-cli" / "secret.key"

_NONCE_SIZE = 12  # 96-bit nonce for AES-256-GCM and ChaCha20-Poly1305
_GCM_TAG_SIZE = 16


class CryptoAlgorithm:
    FERNET = "fernet"
    AES256GCM = "aes256gcm"
    CHACHA20POLY1305 = "chacha20poly1305"


FIPS_ALLOWED = {CryptoAlgorithm.FERNET, CryptoAlgorithm.AES256GCM}


def generate_key(algorithm: str) -> bytes:
    """Return raw key bytes for the given algorithm."""
    if algorithm == CryptoAlgorithm.FERNET:
        return Fernet.generate_key()  # 44-char base64url bytes
    if algorithm in (CryptoAlgorithm.AES256GCM, CryptoAlgorithm.CHACHA20POLY1305):
        return os.urandom(32)
    raise ValueError(f"Unknown algorithm: {algorithm!r}")


def encrypt(plaintext: str, algorithm: str, key_material: bytes) -> str:
    """Encrypt a UTF-8 string; return base64-encoded ciphertext string."""
    data = plaintext.encode()
    if algorithm == CryptoAlgorithm.FERNET:
        return Fernet(key_material).encrypt(data).decode()
    if algorithm == CryptoAlgorithm.AES256GCM:
        nonce = os.urandom(_NONCE_SIZE)
        ct = AESGCM(key_material).encrypt(nonce, data, None)
        # ct already contains ciphertext + 16-byte tag appended by AESGCM
        # Store as nonce || tag || ciphertext  (tag is the last 16 bytes of ct)
        tag = ct[-_GCM_TAG_SIZE:]
        ciphertext = ct[:-_GCM_TAG_SIZE]
        return base64.b64encode(nonce + tag + ciphertext).decode()
    if algorithm == CryptoAlgorithm.CHACHA20POLY1305:
        nonce = os.urandom(_NONCE_SIZE)
        # ChaCha20Poly1305.encrypt returns ciphertext_with_appended_tag
        ct_with_tag = ChaCha20Poly1305(key_material).encrypt(nonce, data, None)
        return base64.b64encode(nonce + ct_with_tag).decode()
    raise ValueError(f"Unknown algorithm: {algorithm!r}")


def decrypt(ciphertext: str, algorithm: str, key_material: bytes) -> str:
    """Decrypt; raise ValueError with a safe message on any failure."""
    try:
        if algorithm == CryptoAlgorithm.FERNET:
            return Fernet(key_material).decrypt(ciphertext.encode()).decode()
        if algorithm == CryptoAlgorithm.AES256GCM:
            raw = base64.b64decode(ciphertext)
            nonce = raw[:_NONCE_SIZE]
            tag = raw[_NONCE_SIZE: _NONCE_SIZE + _GCM_TAG_SIZE]
            ct = raw[_NONCE_SIZE + _GCM_TAG_SIZE:]
            # AESGCM.decrypt expects ciphertext+tag concatenated
            return AESGCM(key_material).decrypt(nonce, ct + tag, None).decode()
        if algorithm == CryptoAlgorithm.CHACHA20POLY1305:
            raw = base64.b64decode(ciphertext)
            nonce = raw[:_NONCE_SIZE]
            ct_with_tag = raw[_NONCE_SIZE:]
            return ChaCha20Poly1305(key_material).decrypt(nonce, ct_with_tag, None).decode()
        raise ValueError(f"Unknown algorithm: {algorithm!r}")
    except (InvalidToken, Exception) as exc:
        raise ValueError("Decryption failed — key may be wrong or data is corrupted.") from exc


def _canonical_key_path() -> Path:
    """Resolve the canonical key file path, migrating legacy paths on first access."""
    if not _KEY_FILE.exists():
        for legacy in (_KEY_FILE_LEGACY, _KEY_FILE_LEGACY2):
            if legacy.exists():
                _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
                _KEY_FILE.write_bytes(legacy.read_bytes())
                if sys.platform != "win32":
                    _KEY_FILE.chmod(0o600)
                break
    return _KEY_FILE


def load_key(algorithm: str) -> bytes:
    """Load the active key from env or key file, auto-generating on first run."""
    # 1. Explicit env var override
    env_key = os.environ.get("ZSCALER_SECRET_KEY")
    if env_key:
        raw = env_key.encode() if isinstance(env_key, str) else env_key
        if algorithm == CryptoAlgorithm.FERNET:
            return raw  # already base64url bytes
        # For non-Fernet, the env var is expected to be base64-encoded raw bytes
        return base64.b64decode(raw)

    # 2. Key stored alongside the DB file (Docker volume)
    db_path_env = os.environ.get("ZSCALER_DB_PATH")
    if db_path_env:
        sibling = Path(db_path_env).parent / "secret.key"
        if sibling.exists():
            raw = sibling.read_bytes().strip()
            if algorithm == CryptoAlgorithm.FERNET:
                return raw
            return base64.b64decode(raw)

    # 3. Default key file (with legacy migration)
    key_path = _canonical_key_path()
    if key_path.exists():
        raw = key_path.read_bytes().strip()
        if algorithm == CryptoAlgorithm.FERNET:
            return raw
        return base64.b64decode(raw)

    # 4. First run — generate and save
    new_key = generate_key(algorithm)
    save_key(new_key, algorithm)
    return new_key


def get_active_algorithm() -> str:
    """Return the active encryption algorithm without touching the database.

    Reads ZSCALER_ENCRYPTION_ALGORITHM env var, defaulting to fernet.
    This avoids the circular import that would result from calling get_session()
    inside db/database.py (which is not yet initialised when _derive_sqlcipher_key
    is called during engine creation).
    """
    return os.environ.get("ZSCALER_ENCRYPTION_ALGORITHM", CryptoAlgorithm.FERNET)


def save_key(key_material: bytes, algorithm: str) -> None:
    """Atomically write key_material to the active key file path.

    Mirrors the resolution order in load_key() so the written file is always
    the one that will be read back: ZSCALER_DB_PATH sibling takes priority over
    the default ~/.config path.
    """
    if algorithm == CryptoAlgorithm.FERNET:
        encoded = key_material  # already base64url
    else:
        encoded = base64.b64encode(key_material)

    db_path_env = os.environ.get("ZSCALER_DB_PATH")
    if db_path_env:
        key_path = Path(db_path_env).parent / "secret.key"
    else:
        key_path = _canonical_key_path()

    key_path.parent.mkdir(parents=True, exist_ok=True)

    tmp = key_path.with_suffix(".key.tmp")
    tmp.write_bytes(encoded)
    if sys.platform != "win32":
        tmp.chmod(0o600)
    os.replace(tmp, key_path)
