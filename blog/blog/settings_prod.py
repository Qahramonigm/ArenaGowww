import os
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlparse

from .settings import *

DEBUG = False
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'arenago.example').split(',')

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable must be set to a cryptographically random string")

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable must be set")

db_config = urlparse(DATABASE_URL)
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
            'options': '-c statement_timeout=30000',
        }
    }
}

# ============================================================================
# REDIS CONFIGURATION (Channel Layer + Cache)
# ============================================================================

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [REDIS_URL],
            'capacity': 1500,  # Max channel layer messages before dropping
            'expiry': 10,  # Default group expiry in seconds
            'group_expiry': 86400,  # 24 hours
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
            'IGNORE_EXCEPTIONS': False,  # Fail hard if Redis is down
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            }
        }
    }
}

# ============================================================================
# HTTPS & COOKIE SECURITY
# ============================================================================

SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() == 'true'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Session cookies - never transmitted over HTTP
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 1209600  # 2 weeks

# CSRF cookies
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'

# Allowed origins for cross-origin requests
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',')

# ============================================================================
# HSTS & CSP
# ============================================================================

# HSTS: force HTTPS for 1 year (be very careful with this)
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Content Security Policy
SECURE_CONTENT_SECURITY_POLICY = {
    'default-src': ["'self'"],
    'script-src': ["'self'", "'unsafe-inline'"],  # Adjust based on your needs
    'style-src': ["'self'", "'unsafe-inline'"],
    'img-src': ["'self'", 'data:', 'https:'],
    'font-src': ["'self'"],
    'connect-src': ["'self'", "wss://*"],  # Allow WebSocket connections
    'frame-ancestors': ["'none'"],  # Prevent clickjacking
}

# X-Frame-Options
X_FRAME_OPTIONS = 'DENY'

# ============================================================================
# STATIC & MEDIA FILES
# ============================================================================

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, '../static_prod')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, '../media_prod')

# CDN for static assets (optional)
# STATIC_URL = 'https://cdn.arenago.example/static/'

# ============================================================================
# LOGGING CONFIGURATION (JSON format for log aggregation)
# ============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(timestamp)s %(level)s %(name)s %(message)s'
        },
        'standard': {
            'format': '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s'
        }
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'file_django': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/arenago/django.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 10,
            'formatter': 'json',
        },
        'file_security': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/arenago/security.log',
            'maxBytes': 10485760,
            'backupCount': 20,
            'formatter': 'json',
        },
        'file_websocket': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/arenago/websocket.log',
            'maxBytes': 10485760,
            'backupCount': 15,
            'formatter': 'json',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_django'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['file_security'],
            'level': 'INFO',
            'propagate': False,
        },
        'core.middleware': {
            'handlers': ['file_security'],
            'level': 'WARNING',
            'propagate': False,
        },
        'core.consumers': {
            'handlers': ['console', 'file_websocket'],
            'level': 'INFO',
            'propagate': False,
        },
        'core.signals': {
            'handlers': ['file_websocket'],
            'level': 'INFO',
            'propagate': False,
        },
    }
}

# ============================================================================
# SENTRY INTEGRATION (Error & Performance Monitoring)
# ============================================================================

SENTRY_DSN = os.getenv('SENTRY_DSN', '')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            RedisIntegration(),
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR
            ),
        ],
        traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', 0.1)),
        environment=os.getenv('SENTRY_ENVIRONMENT', 'production'),
        send_default_pii=False,
        in_app_include=['blog', 'core'],
    )

# ============================================================================
# RATE LIMITING & SECURITY
# ============================================================================

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 600  # 600 req/min = 10 req/sec
RATE_LIMIT_PUBLIC_PREFIXES = ['/api/', '/support/']
RATE_LIMIT_EXEMPT_PATHS = [
    r'^/health/$',
    r'^/health/ws/$',
    r'^/static/',
    r'^/media/',
]

AUTO_BAN_THRESHOLD = 10  # Ban after 10 violations
AUTO_BAN_SECONDS = 600   # 10 minute bans

# Django-Axes: Brute force protection
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5  # Max failed login attempts
AXES_COOLOFF_TIME = timedelta(hours=1)
AXES_ONLY_USER_FAILURES = False
AXES_LOCKOUT_PARAMETERS = ['username', 'ip_address']
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
AXES_USE_USER_AGENT = True
AXES_CACHE = 'default'  # Use Redis cache

# ============================================================================
# CHANNELS ASGI
# ============================================================================

ASGI_APPLICATION = 'blog.asgi.application'

# WebSocket origin validation
WS_ALLOWED_ORIGINS = os.getenv('WS_ALLOWED_ORIGINS', 'arenago.example').split(',')

# ============================================================================
# REST FRAMEWORK API
# ============================================================================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
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
    ],
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.AcceptHeaderVersioning',
    'ALLOWED_VERSIONS': ['1.0'],
    'VERSION_PARAM': 'version',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour'
    }
}

# ============================================================================
# FILE UPLOAD & TEMP FILES
# ============================================================================

# Maximum upload size: 100MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 104857600
FILE_UPLOAD_TEMP_DIR = '/var/tmp/arenago'

# ============================================================================
# EMAIL CONFIGURATION (SMTP for notifications)
# ============================================================================

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@arenago.example')

# ============================================================================
# ALLOWED HOST VALIDATION (Extra Security)
# ============================================================================

if not ALLOWED_HOSTS or ALLOWED_HOSTS == ['']:
    raise ValueError("ALLOWED_HOSTS not configured in environment")

# ============================================================================
# PERFORMANCE TUNING
# ============================================================================

# Use a custom connection pool for multi-threaded servers
# Already configured in DATABASES above

# Template caching
TEMPLATES[0]['OPTIONS']['loaders'] = [
    ('django.template.loaders.cached.Loader', [
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader',
    ]),
]

# Middleware optimization
MIDDLEWARE = [
    'django.middleware.gzip.GZipMiddleware',  # Compress responses
] + MIDDLEWARE

# Disable certain middleware for production (optional)
# MIDDLEWARE = [m for m in MIDDLEWARE if m != 'django.middleware.clickjacking.XFrameOptionsMiddleware']

# ============================================================================
# DEPLOYMENT CHECKLIST VERIFICATION
# ============================================================================

import logging
logger = logging.getLogger(__name__)

def run_deployment_checks():
    """Verify production settings are correct"""
    errors = []
    
    if DEBUG:
        errors.append("DEBUG must be False in production")
    
    if not SECRET_KEY or 'insecure' in SECRET_KEY.lower():
        errors.append("SECRET_KEY is not secure")
    
    if not ALLOWED_HOSTS or ALLOWED_HOSTS == ['']:
        errors.append("ALLOWED_HOSTS not configured")
    
    if not SECURE_SSL_REDIRECT:
        logger.warning("SECURE_SSL_REDIRECT is False - consider enabling for production")
    
    if not SECURE_HSTS_SECONDS:
        logger.warning("HSTS not configured - add for production")
    
    if os.getenv('DATABASE_URL', '').startswith('sqlite'):
        errors.append("SQLite database detected - use PostgreSQL for production")
    
    if errors:
        logger.error(f"Production configuration errors: {errors}")
        return False
    
    logger.info("Production configuration verified ✓")
    return True

# Run checks on import
if not run_deployment_checks():
    raise RuntimeError("Production configuration failed checks")
