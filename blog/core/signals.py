from django.contrib.auth.models import User
from .models import UserProfile, FieldCard, SupportTicket, SupportMessage, Booking, TicketItem, TicketConfig, UserTicket
from django.db.models.signals import post_save
from django.dispatch import receiver
from .utils import generate_slots_for_field
from django.contrib.auth.signals import user_login_failed
from django.core.cache import cache
from django.core.mail import mail_admins
import uuid
import logging

try:
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    CHANNELS_ENABLED = True
except ImportError:
    CHANNELS_ENABLED = False

logger = logging.getLogger(__name__)


def broadcast(payload):
    if not CHANNELS_ENABLED:
        return
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            "notify",
            {"type": "broadcast", "payload": payload},
        )
    except Exception:
        logger.exception('Failed to broadcast notification')

logger = logging.getLogger(__name__)


@receiver(user_login_failed)
def handle_login_failed(sender, credentials, request, **kwargs):
    """Detect multiple failed logins and notify admins.

    Uses cache to count failures per username or IP and creates a SupportTicket
    and emails admins when threshold exceeded.
    """
    try:
        username = credentials.get('username') if isinstance(credentials, dict) else None
        ip = None
        if request:
            xff = request.META.get('HTTP_X_FORWARDED_FOR')
            ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')

        key = f"sec:login:{username or ip}"
        window = 300
        threshold = 5
        count = cache.get(key, 0) + 1
        cache.set(key, count, timeout=window)

        if count >= threshold:
            alerted_key = f"sec:login_alerted:{username or ip}"
            if not cache.get(alerted_key):
                try:
                    SupportTicket.objects.create(user=None, phone=ip or username, status='open')
                except Exception:
                    logger.exception('Failed to create SupportTicket for login failures')
                try:
                    mail_admins(
                        'Security alert: repeated failed logins',
                        f"Detected {count} failed logins for {username or ip} within {window} seconds.")
                except Exception:
                    logger.exception('Failed to mail admins for login failures')
                cache.set(alerted_key, 1, timeout=3600)
    except Exception:
        logger.exception('Error in handle_login_failed')


@receiver(post_save, sender=User)
def create_user_ticket(sender, instance, created, **kwargs):
    """Create UserTicket when a new User is created"""
    if created:
        try:
            UserTicket.objects.get_or_create(user=instance)
        except Exception as e:
            logger.exception(f'Failed to create UserTicket for user {instance.id}: {e}')


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile when a new User is created"""
    if created:
        try:
            if instance.username and instance.username.startswith('+'):
                default_phone = instance.username
            else:
                default_phone = f'auto-{uuid.uuid4().hex[:12]}'
            UserProfile.objects.get_or_create(user=instance, defaults={'phone': default_phone})
        except Exception as e:
            logger.exception(f'Failed to create UserProfile for user {instance.id}: {e}')


@receiver(post_save, sender=FieldCard)
def create_field_slots(sender, instance, created, **kwargs):
    if created:
        generate_slots_for_field(instance)


# real-time notification signals
@receiver(post_save, sender=SupportMessage)
def support_message_created(sender, instance, created, **kwargs):
    if not created:
        return

    ticket = instance.ticket
    payload = {
        'event': 'support_message',
        'ticket_id': ticket.id,
        'user_id': ticket.user_id,
        'sender': instance.sender,
        'content': instance.content,
        'created_at': instance.created_at.isoformat(),
    }
    broadcast(payload)


@receiver(post_save, sender=Booking)
def booking_status_updated(sender, instance, created, **kwargs):
    date_value = None
    if instance.date is not None:
        date_value = instance.date.isoformat() if hasattr(instance.date, 'isoformat') else str(instance.date)

    start_time_value = None
    if instance.start_time is not None:
        start_time_value = instance.start_time.isoformat() if hasattr(instance.start_time, 'isoformat') else str(instance.start_time)

    payload = {
        'event': 'booking_updated',
        'booking_id': instance.id,
        'owner_id': instance.field.owner_id if instance.field else None,
        'user_id': instance.user_id,
        'status': instance.status,
        'date': date_value,
        'start_time': start_time_value,
        'total_price': instance.total_price,
    }
    broadcast(payload)


@receiver(post_save, sender=TicketItem)
def ticket_config_updated(sender, instance, created, **kwargs):
    config = instance.config
    items = [{'id': item.type, 'price_coins': item.price_coins} for item in config.items.all()]
    payload = {
        'event': 'ticket_config_updated',
        'items': items,
    }
    broadcast(payload)


@receiver(post_save, sender=TicketConfig)
def ticket_config_changed(sender, instance, created, **kwargs):
    items = [{'id': item.type, 'price_coins': item.price_coins} for item in instance.items.all()]
    payload = {
        'event': 'ticket_config_updated',
        'items': items,
    }
    broadcast(payload)
