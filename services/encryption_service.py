"""Key rotation service — shared by the API endpoint and startup auto-rotation."""

import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from db.database import get_session, get_setting, set_setting
from db.models import TenantConfig
from lib.crypto import (
    CryptoAlgorithm,
    FIPS_ALLOWED,
    decrypt,
    encrypt,
    generate_key,
    load_key,
    save_key,
)

log = logging.getLogger(__name__)


def rotate_key(new_algorithm: str) -> dict:
    """Re-encrypt all TenantConfig secrets with a freshly generated key.

    Returns {"rotated": N, "algorithm": ..., "rotated_at": "..."}.
    Raises ValueError on validation failure, RuntimeError on partial failure.
    """
    valid = {CryptoAlgorithm.FERNET, CryptoAlgorithm.AES256GCM, CryptoAlgorithm.CHACHA20POLY1305}
    if new_algorithm not in valid:
        raise ValueError(f"Unknown algorithm: {new_algorithm!r}")

    fips_on = (get_setting("fips_mode") or "false") == "true"
    if fips_on and new_algorithm not in FIPS_ALLOWED:
        raise ValueError(
            f"Algorithm {new_algorithm!r} is not FIPS-compliant. "
            "Disable FIPS mode or choose fernet / aes256gcm."
        )

    current_algorithm = get_setting("encryption_algorithm") or CryptoAlgorithm.FERNET
    current_key = load_key(current_algorithm)

    with get_session() as session:
        rows = session.query(TenantConfig).all()

        # Decrypt everything first — abort entirely if any row fails
        plaintext_map: list[tuple[int, str]] = []
        for row in rows:
            pt = decrypt(row.client_secret_enc, current_algorithm, current_key)
            plaintext_map.append((row.id, pt))

        new_key = generate_key(new_algorithm)

        # Re-encrypt with the new key
        new_enc_map = [(rid, encrypt(pt, new_algorithm, new_key)) for rid, pt in plaintext_map]

        # Write new ciphertext to DB rows (flush, don't commit yet)
        enc_lookup = dict(new_enc_map)
        for row in rows:
            row.client_secret_enc = enc_lookup[row.id]
        session.flush()

        # Write new key file (atomic); keep a backup of the old key
        key_path = Path.home() / ".config" / "zs-config" / "secret.key"
        db_path_env = os.environ.get("ZSCALER_DB_PATH")
        if db_path_env:
            key_path = Path(db_path_env).parent / "secret.key"

        bak_path = key_path.with_suffix(".key.bak")
        if key_path.exists():
            shutil.copy2(key_path, bak_path)

        try:
            save_key(new_key, new_algorithm)
            session.commit()
        except Exception:
            # Restore the old key file if we wrote the new one before the commit failed
            if bak_path.exists():
                os.replace(bak_path, key_path)
            session.rollback()
            raise RuntimeError(
                "Key file replaced but database commit failed — old key restored from backup. "
                "Re-run rotation."
            )
        finally:
            if bak_path.exists():
                bak_path.unlink(missing_ok=True)

    rotated_at = datetime.utcnow().isoformat()
    set_setting("encryption_algorithm", new_algorithm)
    set_setting("key_last_rotated_at", rotated_at)

    return {"rotated": len(new_enc_map), "algorithm": new_algorithm, "rotated_at": rotated_at}


def rotate_key_if_due() -> None:
    """Called at startup — rotate if auto-rotation interval has elapsed."""
    try:
        interval = int(get_setting("key_rotation_interval_days") or "0")
        if interval == 0:
            return

        last_str = get_setting("key_last_rotated_at") or ""
        if last_str:
            last_dt = datetime.fromisoformat(last_str)
            if datetime.utcnow() - last_dt < timedelta(days=interval):
                return

        algorithm = get_setting("encryption_algorithm") or CryptoAlgorithm.FERNET
        result = rotate_key(algorithm)
        log.info(
            "Auto key rotation: rotated %d secrets, algorithm=%s, at=%s",
            result["rotated"],
            result["algorithm"],
            result["rotated_at"],
        )
    except Exception as exc:
        log.error("Auto key rotation failed: %s — server will continue to start.", exc)
