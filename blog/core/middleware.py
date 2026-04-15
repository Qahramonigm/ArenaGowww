import logging
import time
from datetime import timedelta
from urllib.parse import parse_qs

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from django.http import JsonResponse, HttpResponseForbidden
from django.utils import timezone

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async

from .models import SecurityIncident

logger = logging.getLogger(__name__)


class RateLimitMiddleware(MiddlewareMixin):
    """IP‑based rate‑limiting middleware with auto‑ban and logging.

    Core features:
    1. rate limits anonymous/non‑staff requests based on IP
    2. staff/superusers and exempt paths are ignored
    3. limits only apply to public prefixes when configured
    4. incidents are recorded in ``SecurityIncident`` model
    5. if an IP repeatedly trips the limit (``AUTO_BAN_THRESHOLD``)
       it is marked suspicious and auto‑banned for ``AUTO_BAN_SECONDS``
       (403 responses)
    6. banned IPs are stored both in cache and the model and blocked
       instantly on subsequent requests

    Configuration (settings.py):
        RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_MAX_REQUESTS
        RATE_LIMIT_PUBLIC_PREFIXES
        RATE_LIMIT_EXEMPT_PATHS
        AUTO_BAN_THRESHOLD, AUTO_BAN_SECONDS
        SECURITY_EXEMPT_PATHS  # legacy path list reused for convenience

    **Placement:** must follow
    ``django.contrib.auth.middleware.AuthenticationMiddleware`` in the
    ``MIDDLEWARE`` list so ``request.user`` is available.
    """

    def process_request(self, request):
        # disable entirely during tests
        from django.conf import settings
        if getattr(settings, 'TESTING', False):
            return

        path = request.path or ""
        user = getattr(request, "user", None)
        is_auth = getattr(user, "is_authenticated", False)
        is_staff = getattr(user, "is_staff", False)
        is_super = getattr(user, "is_superuser", False)

        # determine client IP early
        ip = self._get_ip(request)
        if not ip:
            return

        # check for active ban first (cache fast-path)
        ban_key = f"rl:ban:{ip}"
        if cache.get(ban_key):
            return JsonResponse({"detail": "Forbidden"}, status=403)

        # if not in cache, consult model and re‑hydrate cache if still banned
        now = timezone.now()
        try:
            incident = SecurityIncident.objects.filter(ip=ip, banned_until__gt=now).first()
            if incident:
                remaining = (incident.banned_until - now).total_seconds()
                cache.set(ban_key, True, timeout=int(remaining))
                return JsonResponse({"detail": "Forbidden"}, status=403)
        except Exception:
            logger.exception("RateLimitMiddleware: failed to check model ban status")

        # staff/superuser bypass
        if is_auth and (is_staff or is_super):
            return

        # Skip rate limiting during tests
        if getattr(settings, 'TESTING', False):
            return

        # path exemptions (also allow legacy SECURITY_EXEMPT_PATHS)
        exempt_patterns = (
            getattr(settings, "RATE_LIMIT_EXEMPT_PATHS", [])
            + getattr(settings, "SECURITY_EXEMPT_PATHS", [])
        )
        for pat in exempt_patterns:
            if __import__("re").match(pat, path):
                logger.debug(f"RateLimitMiddleware: exempt path {path} matches {pat}")
                return

        # public‑prefix filtering
        prefixes = getattr(settings, "RATE_LIMIT_PUBLIC_PREFIXES", [])
        if prefixes and not any(path.startswith(pref) for pref in prefixes):
            return

        # perform counting in time bucket
        window = getattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)
        maxreq = getattr(settings, "RATE_LIMIT_MAX_REQUESTS", 60)
        bucket = int(time.time() // window)
        key = f"rl:{ip}:{bucket}"

        try:
            count = cache.incr(key)
        except Exception:
            count = cache.get(key, 0) + 1
            try:
                cache.set(key, count, timeout=window)
            except Exception:
                logger.exception("RateLimitMiddleware: cache.set failed")
                return

        if count > maxreq:
            incident = self._record_incident(ip, path)
            # if ban was just applied, respond 403 immediately
            if incident.banned_until and incident.banned_until > now:
                return JsonResponse({"detail": "Forbidden"}, status=403)
            return JsonResponse({"detail": "Too Many Requests"}, status=429)

    def _record_incident(self, ip, path):
        """Increment or create a SecurityIncident and apply auto-ban."""
        now = timezone.now()
        auto_thresh = getattr(settings, "AUTO_BAN_THRESHOLD", 0)
        auto_secs = getattr(settings, "AUTO_BAN_SECONDS", 0)

        incident, created = SecurityIncident.objects.get_or_create(
            ip=ip,
            defaults={"last_path": path, "attempts": 1},
        )
        if not created:
            incident.attempts += 1
            incident.last_path = path

        # check for auto-ban condition
        if auto_thresh > 0 and incident.attempts >= auto_thresh:
            if not incident.banned_until or incident.banned_until <= now:
                incident.banned_until = now + timedelta(seconds=auto_secs)
                # cache the ban for quick lookup
                try:
                    cache.set(f"rl:ban:{ip}", True, timeout=auto_secs)
                except Exception:
                    logger.exception("RateLimitMiddleware: failed to cache ban")
        incident.save()
        return incident

    def _get_ip(self, request):
        """Return client IP handling X-Forwarded-For if present."""
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

class JWTAuthMiddleware:
    """Allow websocket auth by passing JWT token in the query string."""

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, scope):
        return JWTAuthMiddlewareInstance(scope, self.inner)


class JWTAuthMiddlewareInstance:
    def __init__(self, scope, inner):
        self.scope = dict(scope)
        self.inner = inner

    async def __call__(self, receive, send):
        query_string = self.scope.get('query_string', b'').decode('utf-8', errors='ignore')
        params = parse_qs(query_string)
        token = params.get('token', [None])[0]

        if token:
            self.scope['user'] = await database_sync_to_async(self._get_user_from_token)(token) or AnonymousUser()

        return await self.inner(self.scope, receive, send)

    def _get_user_from_token(self, token):
        try:
            from rest_framework_simplejwt.authentication import JWTAuthentication

            auth = JWTAuthentication()
            validated_token = auth.get_validated_token(token)
            return auth.get_user(validated_token)
        except Exception:
            return None

class WebSocketSecurityMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.path.startswith("/ws/"):
            if not request.is_secure() and not getattr(settings, 'DEBUG', False):
                return HttpResponseForbidden("SSL required")


class PermissionsPolicyMiddleware(MiddlewareMixin):
    """Add Permissions-Policy header to allow unload in admin panel."""
    
    def process_response(self, request, response):
        # Allow unload for admin panel inline scripts
        response['Permissions-Policy'] = 'unload=(self)'
        return response
