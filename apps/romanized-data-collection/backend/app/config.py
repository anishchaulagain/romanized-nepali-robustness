import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
# backend/.env wins over the shared .env one level up; real environment variables win over both.
load_dotenv(BACKEND_DIR / '.env')
load_dotenv(BACKEND_DIR.parent / '.env')


def _required(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f'Environment variable {name} is required (see .env.example).')
    return value


DATABASE_URL = os.getenv('DATABASE_URL') or _required('AIVEN_DATABASE_URL')
DATABASE_CA_CERT_PATH = os.getenv('DATABASE_CA_CERT_PATH')  # optional: Aiven CA for full TLS verification
SECRET_KEY = _required('SECRET_KEY')
ADMIN_USERNAME = _required('ADMIN_USERNAME')
ADMIN_PASSWORD = _required('ADMIN_PASSWORD')

def _origin(value: str) -> str:
    """Reduce a pasted URL to a browser origin: no quotes, path or trailing slash; https:// if no scheme."""
    value = value.strip().strip('"\'').strip()
    if value and '://' not in value:
        value = 'https://' + value
    scheme, _, rest = value.partition('://')
    return f"{scheme.lower()}://{rest.split('/')[0].lower()}" if rest else ''


FRONTEND_ORIGINS = [o for o in (_origin(v) for v in os.getenv('FRONTEND_ORIGINS', 'http://localhost:5173').split(','))
                    if o]
APP_URL = os.getenv('APP_URL', FRONTEND_ORIGINS[0] if FRONTEND_ORIGINS else '').strip().strip('"\'').rstrip('/')
WRITERS_PER_UNIT = int(os.getenv('WRITERS_PER_UNIT', '3'))  # independent writers per item (all writers, if fewer)
TOKEN_TTL_HOURS =int(os.getenv('TOKEN_TTL_HOURS', '168'))
SEED_FILE = Path(os.getenv('SEED_FILE', BACKEND_DIR / 'seed' / 'items.json'))

# Notifications: any configured channel is used.
NOTIFY_EMAIL = os.getenv('NOTIFY_EMAIL')
SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_FROM = os.getenv('SMTP_FROM', SMTP_USER or '')
NOTIFY_WEBHOOK_URL = os.getenv('NOTIFY_WEBHOOK_URL')  # Slack / Discord / any JSON webhook

SERVERLESS = bool(os.getenv('VERCEL'))
