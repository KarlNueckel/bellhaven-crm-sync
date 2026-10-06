"""Settings loaded from .env (never commit .env; it holds CRM_TOKEN)."""
import os

from dotenv import load_dotenv

load_dotenv()

SITE_BASE = os.getenv("SITE_BASE", "https://analyst-assessment-production.up.railway.app").rstrip("/")
API_BASE = f"{SITE_BASE}/api/v1"
CRM_TOKEN = os.getenv("CRM_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "bellhaven.db")
