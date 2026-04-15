import json
import logging
import hashlib
import hmac
from datetime import datetime, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import Group, User
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.db.models import Count, Sum
from django.conf import settings
from django.utils import timezone

from .models import (
    FieldCard, FieldStatus, UserType, Booking, BookingStatus, FieldSlot,
    PlatformBalance, OwnerBalance, PaymentMethod, Payment, PaymentStatus,
    SupportTicket, SupportMessage, IdempotencyKey, WebhookLog, UserTicket
)


def _is_owner(user):
    return hasattr(user, "profile") and user.profile.user_type == UserType.OWNER


def _check_owner_access(user, owner_id):
    if isinstance(owner_id, str):
        try:
            owner_id = int(owner_id)
        except (ValueError, TypeError):
            return False

    return user.id == owner_id or user.is_staff


@csrf_exempt
@login_required
def owner_create_field(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    if not _is_owner(request.user):
        return JsonResponse({"detail": "Only owners can add fields"}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    required_fields = ["name", "city", "district", "address", "price_per_hour"]
    for field in required_fields:
        if field not in data:
            return JsonResponse({"detail": f"{field} is required"}, status=400)

    try:
        price = float(data["price_per_hour"])
        if price <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({"detail": "price_per_hour must be a positive number"}, status=400)

    field = FieldCard.objects.create(
        owner=request.user,
        name=data["name"],
        city=data["city"],
        district=data["district"],
        address=data["address"],
        description=data.get("description", ""),
        price_per_hour=price,
        status=FieldStatus.PENDING,
    )

    return JsonResponse({"id": field.id, "status": field.status}, status=201)


@login_required
def owner_my_fields(request):
    if not _is_owner(request.user):
        return JsonResponse({"detail": "Only owners"}, status=403)

    qs = FieldCard.objects.filter(owner=request.user).order_by("-created_at").values(
        "id", "name", "city", "district", "price_per_hour", "status", "admin_note", "created_at"
    )
    return JsonResponse({"results": list(qs)}, status=200)


@require_POST
@login_required
def verify_booking_code(request, booking_id):
    try:
        booking_id = int(booking_id)
    except ValueError:
        return JsonResponse({"error": "Invalid booking ID"}, status=400)

    try:
        code = request.POST.get("code")
        if not code:
            try:
                payload = json.loads(request.body.decode('utf-8') or '{}')
                code = payload.get('code') or payload.get('verificationCode') or payload.get('verification_code')
            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception:
        code = None

    if not code or len(str(code).strip()) != 6:
        return JsonResponse(
            {"error": "Code must be 6 digits"},
            status=400
        )

    try:
        booking = Booking.objects.select_related("field").get(
            id=booking_id,
            field__owner=request.user
        )
    except Booking.DoesNotExist:
        return JsonResponse({"error": "Booking not found"}, status=404)

    now = timezone.now()
    if booking.verification_locked_until and booking.verification_locked_until > now:
        remaining_time = int((booking.verification_locked_until - now).total_seconds() / 60)
        return JsonResponse({
            "error": f"Too many failed attempts. Try again in {remaining_time}m"
        }, status=429)

    if booking.verification_code_hash and check_password(str(code).strip(), booking.verification_code_hash):
        booking.status = BookingStatus.VERIFIED
        booking.verification_attempts = 0
        booking.verification_locked_until = None
        booking.save(update_fields=["status", "verification_attempts", "verification_locked_until"])
        return JsonResponse({"ok": True, "status": booking.status})

    booking.verification_attempts += 1

    if booking.verification_attempts >= 5:
        booking.verification_locked_until = now + timedelta(minutes=15)
        booking.save(update_fields=["verification_attempts", "verification_locked_until"])
        return JsonResponse({
            "error": "Too many failed attempts. Account locked for 15 minutes."
        }, status=429)

    booking.save(update_fields=["verification_attempts"])

    remaining = 5 - booking.verification_attempts
    return JsonResponse({
        "error": "Invalid code",
        "attempts_remaining": remaining
    }, status=400)


@csrf_exempt
@require_POST
@login_required
def create_booking(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    field_id = data.get("field_id") or data.get("fieldId")
    date_str = data.get("date") or data.get("bookingDate")
    slot_ids = data.get("slot_ids") or data.get("slotIds") or []
    start_time_str = data.get("start_time") or data.get("startTime")
    duration_hours = data.get("duration_hours") or data.get("durationHours")

    idempotency_key = request.headers.get('Idempotency-Key') or data.get('idempotency_key')

    if isinstance(field_id, str) and not field_id.strip():
        field_id = None
    if isinstance(date_str, str) and not date_str.strip():
        date_str = None

    if not field_id or not date_str:
        return JsonResponse({
            "detail": "field_id and date are required",
        }, status=400)

    try:
        booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"detail": "date must be YYYY-MM-DD"}, status=400)

    try:
        field_id = int(field_id)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "field_id must be an integer"}, status=400)

    try:
        field = FieldCard.objects.get(id=field_id, status=FieldStatus.APPROVED)
    except FieldCard.DoesNotExist:
        return JsonResponse({"detail": "Field not found or not approved"}, status=404)

    booking = None

    try:
        with transaction.atomic():
            if slot_ids:
                try:
                    slot_ids = [int(sid) for sid in slot_ids]
                except (ValueError, TypeError):
                    return JsonResponse({"detail": "slot_ids must be integers"}, status=400)

                slots = (
                    FieldSlot.objects
                    .select_for_update()
                    .filter(id__in=slot_ids)
                    .select_related("field")
                    .order_by("start_time")
                )

                if slots.count() != len(slot_ids):
                    return JsonResponse({"detail": "Some slots not found"}, status=404)

                first = slots.first()
                if first.field_id != field_id:
                    return JsonResponse({"detail": "Slots belong to another field"}, status=400)

                booked_slots = [s for s in slots if s.is_booked]
                if booked_slots:
                    return JsonResponse({
                        "detail": "Some slots are already booked",
                        "busy_slots": [s.id for s in booked_slots]
                    }, status=409)

                for s in slots:
                    if s.field_id != field_id or s.date != booking_date:
                        return JsonResponse({
                            "detail": "Slots must be same field and same date"
                        }, status=400)

                if first.field.status != FieldStatus.APPROVED:
                    return JsonResponse({
                        "detail": "Field is not approved"
                    }, status=403)

                times = [s.start_time.hour for s in slots]
                for i in range(1, len(times)):
                    if times[i] != times[i - 1] + 1:
                        return JsonResponse({
                            "detail": "Slots must be consecutive hours"
                        }, status=400)

                booking = Booking.objects.create(
                    field=first.field,
                    user=request.user,
                    date=booking_date,
                    start_time=slots.first().start_time,
                    duration_hours=len(slot_ids),
                    status=BookingStatus.WAITING_PAYMENT,
                )

                for s in slots:
                    s.is_booked = True
                    s.booking = booking
                    s.save(update_fields=["is_booked", "booking"])
            else:
                if not start_time_str or duration_hours is None:
                    return JsonResponse({
                        "detail": "start_time and duration_hours required when slot_ids not provided"
                    }, status=400)
                try:
                    booking_time = datetime.strptime(start_time_str, "%H:%M").time()
                except ValueError:
                    return JsonResponse({
                        "detail": "start_time must be HH:MM"
                    }, status=400)

                try:
                    duration_hours = int(duration_hours)
                except (TypeError, ValueError):
                    return JsonResponse({
                        "detail": "duration_hours must be an integer"
                    }, status=400)

                if duration_hours < 1:
                    return JsonResponse({
                        "detail": "duration_hours must be >= 1"
                    }, status=400)

                exists = Booking.objects.filter(
                    field=field,
                    date=booking_date,
                    start_time=booking_time,
                    status__in=[BookingStatus.WAITING_PAYMENT, BookingStatus.VERIFIED]
                ).exists()
                if exists:
                    return JsonResponse({
                        "detail": "This time slot is already booked"
                    }, status=409)

                booking = Booking.objects.create(
                    field=field,
                    user=request.user,
                    date=booking_date,
                    start_time=booking_time,
                    duration_hours=duration_hours,
                    status=BookingStatus.WAITING_PAYMENT,
                )

            # Apply ticket discount if provided
            # Discount applies ONLY to field price (subtotal), NOT to commission
            ticket = data.get('ticket')
            if ticket and ticket in ['ten', 'twenty', 'fifty', 'free']:
                # First check if user has the ticket
                user_tickets, _ = UserTicket.objects.get_or_create(user=request.user)
                if not user_tickets.decrement_ticket(ticket):
                    # User doesn't have this ticket type
                    return JsonResponse({
                        "detail": f"You don't have {ticket} tickets"
                    }, status=400)
                
                # User has the ticket, apply discount
                discount_pct = {
                    'ten': 0.10,
                    'twenty': 0.20,
                    'fifty': 0.50,
                    'free': 1.0
                }.get(ticket, 0)
                
                # Apply discount to subtotal only
                discounted_subtotal = int(booking.subtotal * (1 - discount_pct))
                
                # Update booking: discounted subtotal, fixed service_fee
                booking.subtotal = discounted_subtotal
                booking.owner_amount = discounted_subtotal  # Owner gets discounted subtotal
                booking.service_fee = 5000  # Commission stays fixed
                booking.total_price = booking.subtotal + booking.service_fee
                booking.ticket_used = ticket  # Store which ticket was used
                
                # Ticket already decremented above

            Payment.objects.create(
                booking=booking,
                method=PaymentMethod.CLICK,
                amount=booking.total_price
            )

            if idempotency_key:
                IdempotencyKey.objects.create(
                    key=idempotency_key,
                    user=request.user,
                    booking=booking,
                    response_code=201,
                    response_body=json.dumps({
                        "id": booking.id,
                        "fieldId": booking.field_id,
                        "totalPrice": booking.total_price,
                    })
                )

    except Exception as e:
        logging.error(f"Booking creation error: {e}")
        return JsonResponse({"detail": "Failed to create booking"}, status=500)

    image_url = None
    try:
        if booking.field.image and booking.field.image.name:
            if booking.field.image.storage.exists(booking.field.image.name):
                image_url = booking.field.image.url
    except Exception:
        pass

    # Get updated ticket counts if user has them
    user_tickets = None
    try:
        user_tickets = UserTicket.objects.get(user=request.user)
    except UserTicket.DoesNotExist:
        pass

    return JsonResponse({
        "id": booking.id,
        "fieldId": booking.field_id,
        "fieldName": booking.field.name,
        "location": f"{booking.field.city}, {booking.field.district}",
        "image": image_url,
        "userId": booking.user_id,
        "date": booking.date.isoformat(),
        "time": booking.start_time.strftime("%H:%M"),
        "duration": booking.duration_hours,
        "totalPrice": booking.total_price,
        "verificationCode": booking.verification_code,
        "status": booking.status,
        "ticketCounts": {
            "ten": user_tickets.tickets_ten if user_tickets else 0,
            "twenty": user_tickets.tickets_twenty if user_tickets else 0,
            "fifty": user_tickets.tickets_fifty if user_tickets else 0,
            "free": user_tickets.tickets_free if user_tickets else 0,
        } if user_tickets else None,
    }, status=201)


@require_GET
def field_available_slots(request, field_id):
    """Public API endpoint - no authentication required for slot availability"""
    try:
        field_id = int(field_id)
    except ValueError:
        return JsonResponse({"detail": "Invalid field ID"}, status=400)

    date_str = request.GET.get("date")

    if not date_str:
        return JsonResponse({"detail": "date required"}, status=400)

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"detail": "invalid date"}, status=400)

    try:
        FieldCard.objects.get(id=field_id)
    except FieldCard.DoesNotExist:
        return JsonResponse({"detail": "Field not found"}, status=404)

    booked_hours = set(
        FieldSlot.objects
        .filter(field_id=field_id, date=date, is_booked=True)
        .values_list('start_time', flat=True)
    )

    book_conflicts = Booking.objects.filter(
        field_id=field_id,
        date=date,
        status__in=[BookingStatus.WAITING_PAYMENT, BookingStatus.VERIFIED, BookingStatus.COMPLETED]
    )

    for booking in book_conflicts:
        start_hour = booking.start_time.hour
        for h in range(start_hour, start_hour + booking.duration_hours):
            booked_hours.add(h)

    slots_map = {
        s.start_time.hour: s
        for s in FieldSlot.objects.filter(field_id=field_id, date=date)
    }

    # Build booked-by map from explicit FieldSlot booking and from active bookings
    booked_by = {}

    for s in FieldSlot.objects.filter(field_id=field_id, date=date, is_booked=True).select_related('booking__user'):
        if s.booking_id and s.booking and s.booking.user:
            booked_by[s.start_time.hour] = s.booking.user.username

    for booking in book_conflicts:
        start_hour = booking.start_time.hour
        for h in range(start_hour, start_hour + booking.duration_hours):
            if h not in booked_by and booking.user:
                booked_by[h] = booking.user.username

    slots = []
    for hour in range(8, 23):
        slot_obj = slots_map.get(hour)
        is_booked = hour in booked_hours
        slots.append({
            'slot_id': slot_obj.id if slot_obj else None,
            'start_time': f"{hour:02}:00",
            'is_booked': is_booked,
            'booked_by': booked_by.get(hour),
        })

    return JsonResponse({'slots': slots})


@require_GET
@login_required
def my_bookings(request):
    status = request.GET.get("status", "all")

    qs = (
        Booking.objects
        .select_related("field")
        .filter(user=request.user)
        .order_by("-created_at")
    )

    if status != "all":
        qs = qs.filter(status=status)

    data = []
    for b in qs:
        data.append({
            "id": b.id,
            "field_id": b.field_id,
            "field_name": b.field.name,
            "date": b.date.isoformat(),
            "start_time": b.start_time.strftime("%H:%M"),
            "duration_hours": b.duration_hours,
            "subtotal": b.subtotal,
            "service_fee": b.service_fee,
            "total_price": b.total_price,
            "status": b.status,
            "payment_status": b.payment_status,
            "verification_code": b.verification_code,
            "created_at": b.created_at.isoformat(),
        })

    return JsonResponse({"results": data}, status=200)


@csrf_exempt
@require_POST
@login_required
def cancel_booking(request, booking_id):
    try:
        booking_id = int(booking_id)
    except ValueError:
        return JsonResponse({"detail": "Invalid booking ID"}, status=400)

    try:
        with transaction.atomic():
            booking = (
                Booking.objects
                .select_for_update()
                .select_related("field")
                .get(id=booking_id, user=request.user)  
            )

            if booking.status == BookingStatus.CANCELLED:
                return JsonResponse({"ok": True, "status": booking.status}, status=200)

            if booking.status in [BookingStatus.COMPLETED]:
                return JsonResponse({"detail": "Completed booking cannot be cancelled"}, status=400)

            slots = (
                FieldSlot.objects
                .select_for_update()
                .filter(booking=booking, is_booked=True)
            )

            slots.update(is_booked=False, booking=None)

            booking.status = BookingStatus.CANCELLED
            booking.save(update_fields=["status"])

    except Booking.DoesNotExist:
        return JsonResponse({"detail": "Booking not found"}, status=404)
    except Exception as e:
        logging.error(f"Cancel booking error: {e}")
        return JsonResponse({"detail": "Failed to cancel booking"}, status=500)

    return JsonResponse({"ok": True, "status": booking.status}, status=200)


@require_GET
@login_required
def owner_bookings(request):
    if not _is_owner(request.user):
        return JsonResponse({"detail": "Only owners"}, status=403)

    bookings = (
        Booking.objects
        .select_related("field", "user__profile")
        .filter(field__owner=request.user)
        .order_by("-created_at")
    )

    data = []

    for b in bookings:
        data.append({
            "id": b.id,
            "field": b.field.name,
            "user": b.user.username,
            "phone": getattr(b.user.profile, "phone", ""),
            "date": b.date.isoformat(),
            "start_time": b.start_time.strftime("%H:%M"),
            "duration": b.duration_hours,
            "subtotal": b.subtotal,
            "service_fee": b.service_fee,
            "total": b.total_price,
            "status": b.status,
            "verification_code": b.verification_code,
        })

    return JsonResponse({"results": data})


@require_POST
@login_required
def complete_booking(request, booking_id):
    if not _is_owner(request.user):
        return JsonResponse({"detail": "Only owners"}, status=403)

    try:
        booking_id = int(booking_id)
    except ValueError:
        return JsonResponse({"detail": "Invalid booking ID"}, status=400)

    try:
        booking = Booking.objects.get(
            id=booking_id,
            field__owner=request.user
        )
    except Booking.DoesNotExist:
        return JsonResponse({"detail": "Booking not found"}, status=404)

    if booking.status == BookingStatus.COMPLETED:
        return JsonResponse({"detail": "Already completed"})

    booking.status = BookingStatus.COMPLETED
    booking.save(update_fields=["status"])

    if not booking.field.owner:
        return JsonResponse({"ok": True})

    owner_balance, _ = OwnerBalance.objects.get_or_create(
        owner=booking.field.owner
    )

    owner_income = booking.subtotal

    owner_balance.total_earned += owner_income
    owner_balance.available_balance += owner_income
    owner_balance.save()

    balance, _ = PlatformBalance.objects.get_or_create(id=1)
    balance.total_earnings += booking.service_fee
    balance.save()

    return JsonResponse({
        "ok": True,
        "platform_earned": booking.service_fee
    })


@csrf_exempt
@require_POST
def click_webhook(request):
    transaction_id = request.POST.get("click_trans_id")
    booking_id = request.POST.get("merchant_trans_id")
    sign_string = request.POST.get("sign_string", "")
    sign_time = request.POST.get("sign_time", "")

    CLICK_MERCHANT_SECRET = getattr(settings, 'CLICK_MERCHANT_SECRET', '')
    CLICK_MERCHANT_ID = getattr(settings, 'CLICK_MERCHANT_ID', '')

    if CLICK_MERCHANT_SECRET:
        expected_sign = hashlib.md5(
            f"{CLICK_MERCHANT_ID}{transaction_id}{sign_time}{CLICK_MERCHANT_SECRET}".encode()
        ).hexdigest()

        if sign_string != expected_sign:
            logging.warning(f"Click webhook signature mismatch: txn={transaction_id}")
            return JsonResponse({"error": -1}, status=400)

    try:
        booking_id = int(booking_id)
    except (ValueError, TypeError):
        return JsonResponse({"error": -1}, status=400)

    try:
        with transaction.atomic():
            webhook_log, created = WebhookLog.objects.select_for_update().get_or_create(
                provider='click',
                transaction_id=transaction_id,
                defaults={
                    'status': 'pending',
                    'payload': dict(request.POST)
                }
            )

            if webhook_log.status == 'completed':
                logging.info(f"Click webhook already processed: txn={transaction_id}")
                return JsonResponse({"error": 0})

            if webhook_log.status == 'processing':
                return JsonResponse({"error": -3}, status=202)

            webhook_log.status = 'processing'
            webhook_log.save(update_fields=['status'])

            try:
                payment = Payment.objects.select_for_update().get(
                    booking_id=booking_id
                )
            except Payment.DoesNotExist:
                webhook_log.status = 'failed'
                webhook_log.error_message = f'Payment not found for booking {booking_id}'
                webhook_log.save(update_fields=['status', 'error_message'])
                return JsonResponse({"error": -1}, status=404)

            if payment.status == PaymentStatus.PAID:
                webhook_log.status = 'completed'
                webhook_log.booking = payment.booking
                webhook_log.processed_at = timezone.now()
                webhook_log.save(update_fields=['status', 'booking', 'processed_at'])
                return JsonResponse({"error": 0})

            payment.status = PaymentStatus.PAID
            payment.provider_transaction_id = transaction_id
            payment.paid_at = timezone.now()
            payment.save(update_fields=["status", "provider_transaction_id", "paid_at"])

            booking = payment.booking
            booking.payment_status = PaymentStatus.PAID
            booking.status = BookingStatus.VERIFIED
            booking.save(update_fields=["payment_status", "status"])

            webhook_log.status = 'completed'
            webhook_log.booking = booking
            webhook_log.processed_at = timezone.now()
            webhook_log.save(update_fields=['status', 'booking', 'processed_at'])

            logging.info(f"Click payment processed: booking={booking_id}, txn={transaction_id}")

        return JsonResponse({"error": 0})
    except Exception as e:
        logging.error(f"Click webhook error: {e}", exc_info=True)
        return JsonResponse({"error": -2}, status=500)


def _is_support_agent(user):
    return user.is_active and (user.is_superuser or user.groups.filter(name="support").exists())


@require_GET
def support_info(request):
    return JsonResponse({
        "email": getattr(settings, "SUPPORT_EMAIL", "support@arenago.example"),
        "phone": getattr(settings, "SUPPORT_PHONE", "+998901234567"),
    })


@require_GET
@login_required
def support_page(request):
    return render(request, "support.html", {
        "user_id": request.user.id if request.user.is_authenticated else None,
    })


@require_GET
@login_required
def support_conversation(request):
    ticket = (
        SupportTicket.objects
        .filter(user=request.user)
        .order_by("-created_at")
        .first()
    )
    if not ticket:
        return JsonResponse({"messages": []})

    msgs = ticket.messages.order_by("created_at").values(
        "sender", "content", "created_at"
    )
    result = [
        {
            "sender": m["sender"],
            "content": m["content"],
            "created_at": m["created_at"].isoformat(),
        }
        for m in msgs
    ]
    return JsonResponse({"messages": result})


def support_agent_login(request):
    if request.method == "GET":
        return render(request, "support_agent_login.html")

    username = request.POST.get("username")
    password = request.POST.get("password")
    user = authenticate(request, username=username, password=password)
    if user is not None and _is_support_agent(user):
        auth_login(request, user)
        return redirect("support_agent_panel")
    Group.objects.get_or_create(name="support")
    return render(request, "support_agent_login.html", {"error": "Invalid credentials or not a support agent"})


@user_passes_test(_is_support_agent, login_url='support_agent_login')
def support_agent_logout(request):
    auth_logout(request)
    return redirect("support_agent_login")


@user_passes_test(_is_support_agent, login_url='support_agent_login')
@ensure_csrf_cookie
def support_agent_panel(request):
    users_data = []
    tickets = SupportTicket.objects.all()

    for ticket in tickets:
        unread_count = ticket.messages.filter(sender=SupportMessage.SENDER_USER, read=False).count()
        latest_msg = ticket.messages.order_by('-created_at').first()

        if latest_msg:
            users_data.append({
                'ticket': ticket,
                'user': ticket.user,
                'unread_count': unread_count,
                'latest_message': latest_msg.content[:50],
                'latest_time': latest_msg.created_at,
                'phone': ticket.phone
            })

    users_data.sort(key=lambda x: x['latest_time'], reverse=True)

    return render(request, "support_agent_panel.html", {"users_data": users_data})


@user_passes_test(lambda u: u.is_staff)
def admin_stats(request):
    today = timezone.localdate()

    todays_bookings_qs = Booking.objects.filter(date=today)
    todays_bookings = todays_bookings_qs.count()

    todays_revenue = Payment.objects.filter(status=PaymentStatus.PAID, paid_at__date=today).aggregate(total=Sum('amount'))['total'] or 0

    popular = (
        Booking.objects
        .values('field__id', 'field__name')
        .annotate(bookings_count=Count('id'))
        .order_by('-bookings_count')
        .first()
    )
    popular_field = popular['field__name'] if popular else None
    popular_count = popular['bookings_count'] if popular else 0

    active_users_login = User.objects.filter(last_login__date=today).count()

    active_users_booked = Booking.objects.filter(date=today).values('user').distinct().count()

    payments_count = Payment.objects.filter(status=PaymentStatus.PAID, paid_at__date=today).count()

    ctx = {
        'todays_bookings': todays_bookings,
        'todays_revenue': todays_revenue,
        'popular_field': popular_field,
        'popular_count': popular_count,
        'active_users_login': active_users_login,
        'active_users_booked': active_users_booked,
        'payments_count': payments_count,
    }

    return render(request, 'admin_stats.html', ctx)


@user_passes_test(_is_support_agent, login_url='support_agent_login')
def support_agent_reply(request, ticket_id):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        ticket_id = int(ticket_id)
    except ValueError:
        return JsonResponse({"detail": "Invalid ticket ID"}, status=400)

    try:
        ticket = SupportTicket.objects.get(id=ticket_id)
    except SupportTicket.DoesNotExist:
        return JsonResponse({"detail": "Ticket not found"}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    text = data.get("message")
    if not text:
        return JsonResponse({"detail": "message required"}, status=400)

    m = SupportMessage.objects.create(
        ticket=ticket,
        sender=SupportMessage.SENDER_SUPPORT,
        content=text,
        agent=request.user
    )

    return JsonResponse({"ok": True, "message_id": m.id})


@user_passes_test(_is_support_agent, login_url='support_agent_login')
def support_agent_api_tickets(request):
    tickets = SupportTicket.objects.prefetch_related('messages').order_by('-created_at').all()
    result = []
    for t in tickets:
        msgs_qs = t.messages.order_by('created_at')
        msgs = [
            {
                "id": m.id,
                "sender": m.sender,
                "sender_display": m.get_sender_display(),
                "agent_name": m.agent.username if m.agent else None,
                "content": m.content,
                "created_at": m.created_at.strftime("%H:%M"),
            }
            for m in msgs_qs
        ]

        latest_msg = msgs_qs.order_by('-created_at').first()
        unread_count = t.messages.filter(sender=SupportMessage.SENDER_USER, read=False).count()

        result.append({
            "id": t.id,
            "username": t.user.username if t.user else t.phone,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "unread_count": unread_count,
            "latest_message": latest_msg.content[:50] if latest_msg else "",
            "latest_time": latest_msg.created_at.isoformat() if latest_msg else None,
            "messages": msgs,
        })

    result.sort(
        key=lambda x: (
            x.get("latest_time") or "",
            x.get("id", 0),
        ),
        reverse=True,
    )

    return JsonResponse({"tickets": result})


@csrf_exempt
@require_POST
def support_send(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    text = data.get("message")
    if not text:
        return JsonResponse({"detail": "message field required"}, status=400)

    user = request.user if request.user.is_authenticated else None
    phone = getattr(getattr(request.user, "profile", None), "phone", "") if user else data.get("phone", "")

    ticket, created = SupportTicket.objects.get_or_create(
        user=user,
        phone=phone,
        defaults={}
    )

    SupportMessage.objects.create(ticket=ticket, sender=SupportMessage.SENDER_USER, content=text)

    return JsonResponse({"ok": True, "ticket_id": ticket.id})


@user_passes_test(_is_support_agent, login_url='support_agent_login')
@require_GET
def support_agent_conversation(request, ticket_id):
    try:
        ticket_id = int(ticket_id)
    except ValueError:
        return JsonResponse({"detail": "Invalid ticket ID"}, status=400)

    try:
        ticket = SupportTicket.objects.get(id=ticket_id)
    except SupportTicket.DoesNotExist:
        return JsonResponse({"detail": "Ticket not found"}, status=404)

    ticket.messages.filter(sender=SupportMessage.SENDER_USER).update(read=True)

    messages = ticket.messages.order_by('created_at').values(
        'id', 'sender', 'content', 'created_at', 'agent__username'
    )

    result = [
        {
            'id': m['id'],
            'sender': m['sender'],
            'content': m['content'],
            'created_at': m['created_at'].isoformat(),
            'agent_name': m['agent__username']
        }
        for m in messages
    ]

    return JsonResponse({
        'ticket_id': ticket_id,
        'user': ticket.user.username if ticket.user else ticket.phone,
        'phone': ticket.phone if ticket.user else '',
        'email': ticket.user.email if ticket.user else '',
        'messages': result
    })