#!/usr/bin/env bash
#
# Render build script.
#
# Installs dependencies, collects static files, and applies migrations to the
# PostgreSQL database supplied through DATABASE_URL.
#
# Migrations run at build time because Render's pre-deploy command is only
# available on paid plans and this service runs on the free plan.

set -euo pipefail

echo "==> Installing dependencies"
python -m pip install --no-cache-dir --upgrade pip
python -m pip install --no-cache-dir -r requirements.txt

echo "==> Collecting static files"
python manage.py collectstatic --noinput

# --- Database safety guard -------------------------------------------------
# Migrations must only ever be applied to a real PostgreSQL server. This blocks
# accidental runs against the local development db.sqlite3.
DATABASE_URL="${DATABASE_URL:-}"

if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: DATABASE_URL is not set. Refusing to run migrations." >&2
  exit 1
fi

case "$DATABASE_URL" in
  postgres://*|postgresql://*) ;;
  *)
    echo "ERROR: DATABASE_URL is not a PostgreSQL URL. Refusing to run migrations." >&2
    exit 1
    ;;
esac

echo "==> Resolved production database"
python - <<'PY'
import os
from urllib.parse import urlsplit

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SchoolManagement.settings')

from django.conf import settings

config = settings.DATABASES['default']
url = urlsplit(os.environ['DATABASE_URL'])

if not config['ENGINE'].endswith('postgresql'):
    raise SystemExit('ERROR: resolved database engine is not postgresql.')

print(f"    engine: {config['ENGINE']}")
print(f"    host:   {url.hostname}")
print(f"    port:   {url.port or 5432}")
print(f"    name:   {url.path.lstrip('/')}")
print(f"    user:   {url.username}")
PY

echo "==> Applying migrations to PostgreSQL"
python manage.py migrate --noinput

echo "==> Applied migrations"
python manage.py showmigrations

echo "==> Build complete"
