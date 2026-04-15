import os
import sys
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    print("⚠️  WARNING: SECRET_KEY not set. Generate with:")
    print("   python -c 'import secrets; print(secrets.token_urlsafe(50))'")
    print("   Then set in .env file as: SECRET_KEY=<generated-key>")
    SECRET_KEY = "django-insecure-development-only-not-for-production"

DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
OTP_ALLOW_MISSING_SMS_PROVIDER = os.getenv('OTP_ALLOW_MISSING_SMS_PROVIDER', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,0.0.0.0').split(',')
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS if h.strip()]

TESTING = "test" in sys.argv

import importlib.util

_HAS_JAZZMIN = importlib.util.find_spec("jazzmin") is not None
_HAS_AXES = importlib.util.find_spec("axes") is not None

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
]

if _HAS_JAZZMIN:
    INSTALLED_APPS.insert(0, "jazzmin")

if _HAS_AXES:
    INSTALLED_APPS.append("axes")

INSTALLED_APPS.append("core")

# ============================================================================
# MIDDLEWARE CONFIGURATION (Security-first order)
# ============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",  # FIRST: Security headers
    "corsheaders.middleware.CorsMiddleware",          # CORS before common
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",     # CSRF protection
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.RateLimitMiddleware",           # Custom rate limiting
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.PermissionsPolicyMiddleware",   # Security headers
]

if _HAS_AXES:
    # Insert before AuthenticationMiddleware (per django-axes docs)
    MIDDLEWARE.insert(5, "axes.middleware.AxesMiddleware")

# ============================================================================
# JWT & AUTHENTICATION SETTINGS
# ============================================================================

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": True,
    "AUTH_COOKIE": "refresh_token",
    "AUTH_COOKIE_SECURE": os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true',
    "AUTH_COOKIE_HTTP_ONLY": True,
    "AUTH_COOKIE_SAMESITE": "Strict",
}

# ============================================================================
# CORS CONFIGURATION
# ============================================================================

CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:3000,http://127.0.0.1:3000'
).split(',')
CORS_ALLOWED_ORIGINS = [o.strip() for o in CORS_ALLOWED_ORIGINS if o.strip()]

CORS_ALLOW_CREDENTIALS = True

# ============================================================================
# COOKIE & SESSION SECURITY
# ============================================================================

SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'False').lower() == 'true'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 1209600  # 2 weeks

# ============================================================================
# SECURITY HEADERS
# ============================================================================

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# HTTPS redirect (set to True in production)
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'False').lower() == 'true'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS headers (only enable in production)
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
else:
    SECURE_HSTS_SECONDS = 0

# Content Security Policy
SECURE_CONTENT_SECURITY_POLICY = {
    'default-src': ("'self'",),
    'script-src': ("'self'", "'unsafe-inline'"),  # Minimize unsafe-inline
    'style-src': ("'self'", "'unsafe-inline'"),
    'img-src': ("'self'", "data:", "https:"),
    'font-src': ("'self'",),
    'connect-src': ("'self'", "wss://localhost:8000"),  # WebSocket
    'frame-ancestors': ("'none'",),
    'base-uri': ("'self'",),
}

# ============================================================================
# RATE LIMITING & SECURITY
# ============================================================================

RATE_LIMIT_EXEMPT_PATHS = [
    r'^/admin/',
    r'^/support/agent/',
    r'^/static/',
    r'^/media/',
    r'^/payment/click/webhook/',
    r'^/accounts/',  # Django auth views
]

RATE_LIMIT_PUBLIC_PREFIXES = [
    '/api/',  # Rate limit all API endpoints
]

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 100

# Auto-ban repeat offenders
AUTO_BAN_THRESHOLD = 10
AUTO_BAN_SECONDS = 600  # 10 minutes

# django-axes brute-force protection
if _HAS_AXES:
    AXES_ENABLED = True
    AXES_FAILURE_LIMIT = 5
    AXES_COOLOFF_TIME = timedelta(minutes=30)
    AXES_ONLY_USER_FAILURES = False
    AXES_LOCKOUT_PARAMETERS = ['username', 'ip_address']
    AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
    AXES_USE_USER_AGENT = True

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ============================================================================
# PASSWORD VALIDATION
# ============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            'min_length': 10,
        }
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ============================================================================
# INTERNATIONALIZATION
# ============================================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ============================================================================
# STATIC & MEDIA FILES
# ============================================================================

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ============================================================================
# EMAIL CONFIGURATION
# ============================================================================

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@arenago.uz')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')

# ============================================================================
# TEMPLATES
# ============================================================================

ROOT_URLCONF = "blog.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, 'templates')],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "blog.wsgi.application"

# ============================================================================
# CHANNELS & WEBSOCKET
# ============================================================================

ASGI_APPLICATION = "blog.asgi.application"
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# ============================================================================
# JAZZMIN ADMIN UI (Optional)
# ============================================================================

if _HAS_JAZZMIN:
    JAZZMIN_SETTINGS = {
        "site_title": "ArenaGo Admin",
        "site_header": "ArenaGo",
        "site_brand": "ArenaGo",
        "welcome_sign": "ArenaGo administration",
        "show_ui_builder": False,
        "search_model": ["auth.User", "auth.Group"],
    }

# ============================================================================
# REST FRAMEWORK CONFIGURATION
# ============================================================================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': [
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'EXCEPTION_HANDLER': 'rest_framework.views.exception_handler',
}

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'core': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
