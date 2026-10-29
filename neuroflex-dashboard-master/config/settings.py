import os
from pathlib import Path

from dotenv import load_dotenv

from integrations.services.runtime_config import RuntimeConfig

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("NEUROFLEX_DATA_DIR", BASE_DIR))

load_dotenv(DATA_DIR / ".env", override=False)
load_dotenv(BASE_DIR / ".env", override=False)

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-change-me-before-production",
)
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'dashboard',
    'audit',
    'reports',
    'clinical_sessions',
    'terms',
    'updater',
    "offline_mode",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    "offline_mode.middleware.LocalhostOnlyMiddleware",
    "offline_mode.middleware.OfflineModeMiddleware",
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'updater.context_processors.dashboard_version',
                'offline_mode.context_processors.sync_banner',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'db.sqlite3',
    }
}

# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = DATA_DIR / 'media'
PRIVATE_REPORTS_ROOT = DATA_DIR / 'private_reports'
# Empty by default: configure an absolute local JSONL path only on hosts where
# the Wazuh agent is installed and allowed to read the file.
WAZUH_AUDIT_LOG_PATH = os.getenv("WAZUH_AUDIT_LOG_PATH", "")
WAZUH_AUDIT_HASH_KEY = os.getenv("WAZUH_AUDIT_HASH_KEY", "")

AUTH_USER_MODEL = 'accounts.CustomUser'
LOGIN_URL = 'accounts:login'
SESSION_DATA_SOURCE = os.getenv("SESSION_DATA_SOURCE", "local")
SESSION_LOCAL_DATA_PATH = Path(
    os.getenv(
        "SESSION_LOCAL_DATA_PATH",
        DATA_DIR / "clinical_sessions" / "data" / "local_sessions",
    )
)
COGNITIVE_MODEL_DIR = BASE_DIR / "ml" / "model_artifacts"
COGNITIVE_MODEL_MODE = os.getenv("COGNITIVE_MODEL_MODE", "three_class_provisional")
COGNITO_REGION = os.getenv("COGNITO_REGION", "us-east-1")
runtime_config = RuntimeConfig()
COGNITO_CLIENT_ID = runtime_config.get_cognito_client_id() or "change-me"
NEUROFLEX_API_BASE_URL = runtime_config.get_neuroflex_api_base_url() or "change-me"

# --- Modo offline (LAN + sync) ---
OFFLINE_ACCESS_DAYS = int(os.getenv("OFFLINE_ACCESS_DAYS", "15"))
OFFLINE_LOGIN_MAX_ATTEMPTS = 5
OFFLINE_LOGIN_LOCKOUT_MINUTES = 15
PAIRING_PIN_TTL_SECONDS = 180
PAIRING_MAX_PIN_ATTEMPTS = 5
LAN_DISCOVERY_PORT = 48100
LAN_HTTP_PORT = int(os.environ.get("LAN_HTTP_PORT", "8000"))
LAN_DISCOVERY_ENABLED = os.getenv("LAN_DISCOVERY_ENABLED", "1") == "1"
