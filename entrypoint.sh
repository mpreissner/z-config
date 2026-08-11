#!/bin/sh
set -e

if [ "${ZS_TUI_ONLY}" = "1" ]; then
    exec python -m cli.z_config
fi

# Bootstrap SSL from mounted cert files if ZS_SSL_DOMAIN is set.
# Runs every startup so cert rotation takes effect on container restart.
if [ -n "${ZS_SSL_DOMAIN:-}" ] && [ -f "/certs/cert.pem" ] && [ -f "/certs/key.pem" ]; then
    python -c "
import os, shutil, pathlib, sys
sys.path.insert(0, '.')
from db.database import set_setting
from services.ssl_service import public_origin
ssl_dir = pathlib.Path('/data/db/ssl')
ssl_dir.mkdir(parents=True, exist_ok=True)
shutil.copy('/certs/cert.pem', str(ssl_dir / 'cert.pem'))
shutil.copy('/certs/key.pem', str(ssl_dir / 'key.pem'))
os.chmod(str(ssl_dir / 'key.pem'), 0o600)
domain = os.environ['ZS_SSL_DOMAIN']
set_setting('ssl_mode', 'upload')
set_setting('ssl_domain', domain)
set_setting('webauthn_origin', public_origin(domain))
set_setting('webauthn_rp_id', domain)
print(f'SSL bootstrapped from /certs for domain: {domain}')
" || echo "WARNING: SSL bootstrap from /certs failed — check cert files and permissions"
fi

# Determine SSL mode from DB at startup.
# The set of modes that mean "serve TLS" and the cert paths both come from
# ssl_service so this cannot drift out of step with the application.
SSL_CMD=$(python -c "
import sys
sys.path.insert(0, '.')
from db.database import get_setting
from services.ssl_service import _ACTIVE_MODES, CERT_PATH, KEY_PATH
mode = get_setting('ssl_mode') or 'none'
if mode in _ACTIVE_MODES:
    if CERT_PATH.exists() and KEY_PATH.exists():
        domain = get_setting('ssl_domain') or 'localhost'
        print(f'ssl_mode=tls cert={CERT_PATH} key={KEY_PATH} domain={domain}')
        sys.exit(0)
    print(f'WARNING: ssl_mode={mode} but no certificate on disk', file=sys.stderr)
print('ssl_mode=none')
" 2>/dev/null || echo "ssl_mode=none")

case "$SSL_CMD" in
  ssl_mode=tls*)
    CERT=$(echo "$SSL_CMD"   | grep -o 'cert=[^ ]*'   | cut -d= -f2)
    KEY=$(echo "$SSL_CMD"    | grep -o 'key=[^ ]*'    | cut -d= -f2)
    DOMAIN=$(echo "$SSL_CMD" | grep -o 'domain=[^ ]*' | cut -d= -f2)
    ZS_SSL_DOMAIN="${DOMAIN:-localhost}" uvicorn api.redirect_app:redirect_app --host 0.0.0.0 --port 8000 &
    exec python api/run_ssl.py "$CERT" "$KEY"
    ;;
  *)
    exec uvicorn api.main:app --host 0.0.0.0 --port 8000
    ;;
esac
