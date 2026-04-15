"""
ASGI config for blog project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blog.settings")

django_asgi_app = get_asgi_application()

import core.routing
from core.middleware import JWTAuthMiddleware

application = ProtocolTypeRouter({
	"http": django_asgi_app,
	"websocket": AuthMiddlewareStack(
		JWTAuthMiddleware(
			URLRouter(
				core.routing.websocket_urlpatterns
			)
		)
	),
})
