"""Custom permission classes for API endpoints."""
from rest_framework.permissions import BasePermission, IsAuthenticated
from django.contrib.auth.models import Group

class IsSupportAgent(BasePermission):
    message = "Only support agents can access this endpoint."
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.groups.filter(name='support').exists()
        )

class IsAuthenticatedUser(IsAuthenticated):
    """Authenticated user (alias)."""
    pass
