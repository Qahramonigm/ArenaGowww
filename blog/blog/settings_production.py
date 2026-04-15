"""
Production Django Settings for ArenaGo
CRITICAL: Use environment variables for ALL secrets
Generate: python -c 'import secrets; print(secrets.token_urlsafe(50))'

Required environment variables:
    SECRET_KEY - Django secret key (generate above)
    DATABASE_URL - PostgreSQL connection (postgres://user:pass@host:5432/db)
    REDIS_URL - Redis connection (redis://host:6379/0)
    ALLOWED_HOSTS - Comma-separated domain list
    ADMIN_PASSWORD - Admin user password (will be generated if not provided)
"""
import os
import sys
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlparse

# Import base settings
from .settings_secure_dev import *

# ============================================================================
# CRITICAL PRODUCTION SETTINGS
# ============================================================================

DEBUG = False

# 🔒 Validate SECRET_KEY is set
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError(
        "❌ CRITICAL: SECRET_KEY environment variable must be set\n"
        "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(50))'\n"
        "Then export as: export SECRET_KEY=<generated-key>"
    )

# 🔒 ALLOWED_HOSTS from environment
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost').split(',')
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS if h.strip()]

if not ALLOWED_HOSTS:
    raise ValueError("❌ CRITICAL: ALLOWED_HOSTS environment variable must be set")

# ============================================================================
# DATABASE CONFIGURATION (PostgreSQL)
# ============================================================================

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError(
        "❌ CRITICAL: DATABASE_URL environment variable must be set\n"
        "Format: postgres://user:password@host:5432/database"
    )

db_config = urlparse(DATABASE_URL)

if db_config.scheme not in ['postgresql', 'postgres']:
    raise ValueError(
        "❌ CRITICAL: DATABASE_URL must use PostgreSQL\n"
        f"Got scheme: {db_config.scheme}"
    )

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': db_config.path.lstrip('/'),
        'USER': db_config.username,
        'PASSWORD': db_config.password,
        'HOST': db_config.hostname,
        'PORT': db_config.port or 5432,
        'ATOMIC_REQUESTS': True,
        'CONN_MAX_AGE': 600,
        'OPTIONS': {
            'connect_timeout': 10,
            'options': '-c statement_timeout=30000',  # 30 sec timeout
        }
    }
}

# ============================================================================
# REDIS CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [REDIS_URL],
            'capacity': 1500,
            'expiry': 10,
            'group_expiry': 86400,
            'auth_password': os.getenv('REDIS_AUTH_PASSWORD', ''),
        },
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            'IGNORE_EXCEPTIONS': False,
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            }
        }
    }
}

# ============================================================================
# HTTPS & SECURITY
# ============================================================================

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 1209600  # 2 weeks

# HSTS: Enable in production (1 year)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Content Security Policy
SECURE_CONTENT_SECURITY_POLICY = {
    'default-src': ("'self'",),
    'script-src': ("'self'",),  # No unsafe-inline
    'style-src': ("'self'", "'unsafe-inline'"),  # CSS required
    'img-src': ("'self'", "data:", "https:"),
    'font-src': ("'self'",),
    'connect-src': ("'self'", "wss://api.arenago.uz"),
    'frame-ancestors': ("'none'",),
    'base-uri': ("'self'",),
    'form-action': ("'self'",),
}

# ============================================================================
# SECURE DEPLOYMENTCONFIGURATION
# ============================================================================

# Allow additional origins for CORS (from environment)
CORS_ALLOWED_ORIGINS_ENV = os.getenv('CORS_ALLOWED_ORIGINS', '')
if CORS_ALLOWED_ORIGINS_ENV:
    CORS_ALLOWED_ORIGINS = CORS_ALLOWED_ORIGINS_ENV.split(',')
    CORS_ALLOWED_ORIGINS = [o.strip() for o in CORS_ALLOWED_ORIGINS if o.strip()]

# CSRF trusted origins
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in CSRF_TRUSTED_ORIGINS if o.strip()]

# ============================================================================
# STATIC & MEDIA FILES
# ============================================================================

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, '../static_root')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, '../media_root')

# Optional: CDN for static assets
# STATIC_URL = 'https://cdn.arenago.uz/static/'

# ============================================================================
# SECURITY SETTINGS
# ============================================================================

# Rate limiting
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 100

AUTO_BAN_THRESHOLD = 10
AUTO_BAN_SECONDS = 3600  # 1 hour

# Brute-force protection (django-axes)
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=60)
AXES_ONLY_USER_FAILURES = False
AXES_LOCKOUT_PARAMETERS = ['username', 'ip_address']
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
AXES_USE_USER_AGENT = True

# ============================================================================
# LOGGING & MONITORING
# ============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name} {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/arenago/django.log',
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/arenago/security.log',
            'maxBytes': 1024 * 1024 * 10,
            'backupCount': 10,
            'formatter': 'json',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
        },
        'django.security': {
            'handlers': ['security_file', 'mail_admins'],
            'level': 'WARNING',
            'propagate': False,
        },
        'core': {
            'handlers': ['console', 'file', 'security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}

# ============================================================================
# ADMIN SECURITY
# ============================================================================

# Django Admin site configuration
from django.contrib import admin

# Disable admin by setting to False and creating custom path
ENABLE_ADMIN = os.getenv('ENABLE_ADMIN', 'True').lower() == 'true'

if not ENABLE_ADMIN:
    # Admin will be disabled via custom middleware
    pass

# ============================================================================
# EMAIL CONFIGURATION (for production)
# ============================================================================

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@arenago.uz')

# Admins notified of errors
ADMINS = [
    ('Admin', os.getenv('ADMIN_EMAIL', 'admin@arenago.uz')),
]
MANAGERS = ADMINS

# ============================================================================
# ALLOWED_HOSTS SECURITY WARNING
# ============================================================================

if '*' in ALLOWED_HOSTS:
    raise ValueError(
        "❌ CRITICAL: ALLOWED_HOSTS contains '*' (wildcard)\n"
        "This is insecure in production. Set specific domains in .env"
    )

print(f"✅ Production Settings Loaded")
print(f"   DATABASE: {DATABASES['default']['HOST']}")
print(f"   REDIS: {REDIS_URL.split('//')[1] if '//' in REDIS_URL else 'configured'}")
print(f"   ALLOWED_HOSTS: {', '.join(ALLOWED_HOSTS[:2])}")
print(f"   DEBUG: {DEBUG}")
print(f"   HTTPS: {SECURE_SSL_REDIRECT}")
