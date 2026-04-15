from datetime import timedelta
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import json


def set_refresh_cookie(response, refresh_token):
    # Set HttpOnly refresh token cookie
    max_age = int(settings.SIMPLE_JWT.get('REFRESH_TOKEN_LIFETIME', timedelta(days=14)).total_seconds())
    response.set_cookie(
        key="refresh_token",
        value=str(refresh_token),
        httponly=True,
        secure=getattr(settings, 'SESSION_COOKIE_SECURE', False),
        samesite=getattr(settings, 'CSRF_COOKIE_SAMESITE', 'Lax'),
        max_age=max_age,
        path="/",
    )


@csrf_exempt
@require_POST
def token_obtain_pair_cookie(request):
    """Issue access + refresh token; return access in body and refresh as HttpOnly cookie."""
    # Expect frontend to POST user identification (phone/code flow handled elsewhere).
    # This view assumes an authenticated user on request.user set by earlier flow.
    user = request.user
    if not user or not user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)

    refresh = RefreshToken.for_user(user)
    access = refresh.access_token

    resp = Response({"access": str(access)})
    set_refresh_cookie(resp, refresh)
    return resp


@api_view(['POST'])
@permission_classes([AllowAny])
def token_refresh_cookie(request):
    # Read refresh token from cookie OR request body (for cross-origin requests)
    # Allow unauthenticated requests (for initial token refresh after login)
    refresh_token = request.COOKIES.get('refresh_token')
    
    if not refresh_token and request.method == 'POST' and request.data:
        refresh_token = request.data.get('refresh')
    
    if not refresh_token:
        return Response({"detail": "Refresh token missing"}, status=401)
    try:
        refresh = RefreshToken(refresh_token)
        new_access = refresh.access_token

        # If rotation is enabled, create a new refresh token and blacklist old
        if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS'):
            # determine user from token claims
            user_model = get_user_model()
            user_id = refresh.get('user_id') or refresh.get('uid')
            try:
                user = user_model.objects.get(id=user_id)
            except Exception:
                user = None
            if user:
                new_refresh = RefreshToken.for_user(user)
            else:
                new_refresh = None
            resp = Response({"access": str(new_access), "refresh": str(new_refresh) if new_refresh else None})
            if new_refresh:
                set_refresh_cookie(resp, new_refresh)
            return resp

        return Response({"access": str(new_access), "refresh": None})
    except Exception:
        return Response({"detail": "Invalid refresh token"}, status=401)


@api_view(['POST'])
@permission_classes([AllowAny])
def token_blacklist_cookie(request):
    # Blacklist the refresh token and clear cookie
    # Allow unauthenticated users to logout (they just have no token to blacklist)
    refresh_token = request.COOKIES.get('refresh_token')
    
    # Also accept from body as fallback for cross-origin requests
    if not refresh_token and request.method == 'POST' and request.data:
        refresh_token = request.data.get('refresh')
    
    # Attempt to blacklist if token exists
    if refresh_token:
        try:
            r = RefreshToken(refresh_token)
            r.blacklist()
        except Exception:
            pass
    
    resp = Response({"detail": "logged out"})
    resp.delete_cookie('refresh_token', path='/')
    return resp



