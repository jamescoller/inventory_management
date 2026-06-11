"""
Django settings for inventory_management_site project.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

import os
import warnings
from pathlib import Path

from decouple import config
from django.contrib.messages import constants as messages

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Ignore the stupid brother_ql depreciation warning
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=".*brother_ql.devicedependent is deprecated.*",
)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config("DJANGO_SECRET_KEY", default=None)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=False, cast=bool)

ENABLE_BARCODE_PRINTING = config("ENABLE_BARCODE_PRINTING", default=True, cast=bool)

# Public base URL used to build absolute links encoded in QR labels (Phase 12).
# Non-secret; overridable per-environment via docker-compose `environment:`.
SITE_BASE_URL = config("SITE_BASE_URL", default="https://inventory.home.collerco.com")

BARCODE_FONT_PATH = BASE_DIR / "fonts" / "DejaVuSans.ttf"
BARCODE_FONT_SIZE = 22  # or 12 / 16 etc.

ALLOWED_HOSTS = [
    "inventory.home",
    "inventory.home.collerco.com",
    "knowledge.local",
    "inventory-manager",
    "10.10.20.17",
    "10.10.20.12",
    "10.10.20.2",
]

# Application definition

INSTALLED_APPS = [
    # django-unfold admin theme. These MUST precede ``django.contrib.admin`` so
    # Unfold's template overrides win. The contrib apps style third-party admin
    # add-ons: ``simple_history`` (history views), ``forms`` (admin form widgets),
    # ``filters`` (changelist filter widgets). ``simple_history`` must sit before
    # the ``simple_history`` app itself (below) per Unfold's docs.
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.simple_history",
    "inventory",
    "crispy_forms",
    "crispy_bootstrap5",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "polymorphic",
    "simple_history",
]

if DEBUG:
    INSTALLED_APPS += ["debug_toolbar"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

ROOT_URLCONF = "inventory_management_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "inventory_management_site.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.1/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        # Dev: defaults to the repo-root DB (unchanged). Prod sets SQLITE_DB_PATH
        # in docker-compose.yml's `environment:` to /app/db/inventory_db.sqlite3 (the
        # mounted DB directory) so WAL's -wal/-shm siblings are shareable across
        # containers (Phase 16.1). It lives in compose, not ~/.env_inventory, because
        # that file is root-owned on the app LXC; a path isn't a secret anyway.
        "NAME": config(
            "SQLITE_DB_PATH", default=str(BASE_DIR / "inventory_db.sqlite3")
        ),
    }
}

# Location of local barcode printer
PRINTER_IP = config("PRINTER_IP", default=None)

# Designates IPs for internal user testing / dev testing
INTERNAL_IPS = [
    # ...
    "127.0.0.1",
    # ...
]


# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

CSRF_TRUSTED_ORIGINS = [
    # Port 8000 for local test deployments only
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    # Port 8080 on the LXC
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://knowledge.local:8080",
    "http://10.10.20.17:8080",
    # Via NGINX
    "http://inventory.home",
    "https://inventory.home.collerco.com",
]


# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "America/Detroit"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/

STATIC_URL = "static/"

# Define this only for collectstatic use
STATIC_ROOT = BASE_DIR / "staticfiles"

# Use this to find app-level static files during development
STATICFILES_DIRS = [
    BASE_DIR / "inventory/static",
]


# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"
# NOTE: crispy stays on bootstrap5 — that pack styles the *public* site forms.
# Unfold ships an ``unfold_crispy`` pack for the admin, but switching the global
# CRISPY_TEMPLATE_PACK would restyle the front-end. The admin gets Unfold widget
# styling via ``unfold.contrib.forms`` regardless of the crispy pack.

# ----- django-unfold admin theme -----------------------------------------
# Drop-in modern admin theme. Auto dark mode (no THEME key = OS-preference
# switcher enabled). Primary colour mirrors the public site's Bootswatch Zephyr
# blue (#3459e6) as a Tailwind 50–950 scale; Unfold accepts space-separated
# "R G B" triplets and normalises them to rgb(). The 600 shade is the exact
# brand anchor. ``DASHBOARD_CALLBACK`` injects live KPI cards into the landing
# page (templates/admin/index.html).
UNFOLD = {
    "SITE_TITLE": "Inventory",
    "SITE_HEADER": "Inventory",
    "SHOW_HISTORY": True,
    "DASHBOARD_CALLBACK": "inventory.admin_dashboard.dashboard_callback",
    "COLORS": {
        "primary": {
            "50": "243 245 254",
            "100": "226 232 253",
            "200": "187 201 251",
            "300": "139 162 249",
            "400": "92 124 245",
            "500": "65 100 234",
            "600": "52 89 230",  # #3459e6 — Zephyr brand anchor
            "700": "31 64 189",
            "800": "31 56 150",
            "900": "31 50 122",
            "950": "23 35 79",
        },
    },
}

LOGIN_REDIRECT_URL = "/"
LOGIN_URL = "login"

LOW_QUANTITY = 3

MESSAGE_TAGS = {
    messages.ERROR: "danger",
}

LOGGING = {
    "version": 1,  # The dictConfig version
    "disable_existing_loggers": False,  # retain the default loggers
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
        "file": {
            "class": "logging.FileHandler",
            "filename": os.path.join(BASE_DIR, "inventory.log"),
            "level": "DEBUG",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "WARNING",
        },
        "inventory": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
    "formatters": {
        "verbose": {
            "format": "{name} {levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{levelname}] {message}",
            "style": "{",
        },
    },
}
