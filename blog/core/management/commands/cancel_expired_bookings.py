from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from .models import Booking, BookingStatus, PaymentStatus, FieldSlot


class Command(BaseCommand):
    help = "Cancel unpaid bookings that exceeded payment deadline and free their slots."

    def handle(self, *args, **options):
        now = timezone.now()

        qs = Booking.objects.filter(
            status=BookingStatus.WAITING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            payment_expires_at__isnull=False,
            payment_expires_at__lte=now,
        ).values_list("id", flat=True)

        cancelled_count = 0

        for booking_id in qs:
            with transaction.atomic():
                # bookingni lock qilamiz
                booking = (
                    Booking.objects.select_for_update()
                    .get(id=booking_id)
                )

                # qayta tekshir (race condition bo'lmasin)
                if booking.status != BookingStatus.WAITING_PAYMENT:
                    continue
                if booking.payment_status != PaymentStatus.PENDING:
                    continue
                if not booking.payment_expires_at or booking.payment_expires_at > now:
                    continue

                # slotlarni bo'shatamiz
                FieldSlot.objects.select_for_update().filter(
                    booking=booking,
                    is_booked=True
                ).update(is_booked=False, booking=None)

                # booking cancel
                booking.status = BookingStatus.CANCELLED
                booking.payment_status = PaymentStatus.CANCELLED
                booking.save(update_fields=["status", "payment_status"])

                # payment ham cancel (agar bor bo'lsa)
                if hasattr(booking, "payment"):
                    booking.payment.status = PaymentStatus.CANCELLED
                    booking.payment.save(update_fields=["status"])

                cancelled_count += 1

        self.stdout.write(self.style.SUCCESS(f"Cancelled expired bookings: {cancelled_count}"))