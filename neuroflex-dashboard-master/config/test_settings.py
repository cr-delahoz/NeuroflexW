from config.settings import *
import os
from pathlib import Path

DEBUG = False

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

MIGRATION_MODULES = {
    "admin": None,
    "auth": None,
    "contenttypes": None,
    "sessions": None,
    "messages": None,
    "staticfiles": None,
    "accounts": None,
    "audit": None,
    "clinical_sessions": None,
    "dashboard": None,
    "reports": None,
    "terms": None,
    "updater": None,
}

DATA_DIR = Path(os.getenv("NEUROFLEX_DATA_DIR", BASE_DIR))
