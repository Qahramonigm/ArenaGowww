import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import Group
from django.core.cache import cache
from asgiref.sync import async_to_sync

from .models import SupportTicket, SupportMessage, Booking, Payment


class IncidentsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("incidents", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("incidents", self.channel_name)

    async def incident_message(self, event):
        # event['data'] should be serializable
        await self.send(text_data=json.dumps(event.get("data", {})))


# ---------------------------------------------------------------------------
# notify consumer for unread counts and broadcasting events to agents/admins
# ---------------------------------------------------------------------------

def rate_limit_key(user):
    return f"rl:{user.pk}"


class NotifyConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer that pushes unread counts for admin/support agents.
    All agents connect to group 'notify'.  Messages from DB signals broadcast
    to the group.  Individual users may also join private groups if needed.
    """

    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Allow all authenticated users to subscribe to update notifications.
        if not (await database_sync_to_async(self._is_authorized_user)()):
            await self.close()
            return

        await self.accept()
        self.group_name = "notify"
        await self.channel_layer.group_add(self.group_name, self.channel_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content):
        """
        Optional client messages: we ignore or respond to ping.
        Apply basic rate‑limit.
        """
        # rate limiting
        key = rate_limit_key(self.user)
        count = cache.get(key, 0)
        if count > 20:
            await self.close(code=4403)  # too many requests
            return
        cache.set(key, count + 1, 1)

        typ = content.get("type")
        if typ == "ping":
            await self.send_json({"type": "pong"})
        else:
            # ignore unexpected messages
            pass

    async def broadcast(self, event):
        payload = event.get("payload", {})
        await self.send_json(payload)

    @staticmethod
    def _is_authorized_user():
        return True


# helpers used by signals to push notifications ----------------------------------
UNREAD_CACHE_KEY = "support:unread_total"


def unread_total():
    val = cache.get(UNREAD_CACHE_KEY)
    if val is None:
        val = SupportTicket.objects.filter(
            messages__sender=SupportMessage.SENDER_USER,
            messages__read=False,
        ).distinct().count()
        cache.set(UNREAD_CACHE_KEY, val, 5)
    return val


def broadcast(payload):
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            "notify",
            {"type": "broadcast", "payload": payload},
        )
    except Exception:
        # do not break connection on failure
        import logging

        logging.getLogger(__name__).exception("Error broadcasting payload")

