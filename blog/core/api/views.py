"""
Fixed API Views with proper security:
1. Remove @csrf_exempt - use Django's built-in CSRF protection
2. Add input validation using DRF Serializers
3. Add permission classes
4. Proper error handling
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
import json
import logging
import base64
import re
import uuid

from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.conf import settings
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from datetime import datetime, date, time, timedelta

from ..models import Amenity, FieldCard, FieldImage, FieldStatus, Booking, BookingStatus, FieldSlot, Review, OTPCode, OTPRateLimit, UserType, UserProfile
from .serializers import (
    FieldCardSerializer,
    BookingSerializer,
)

logger = logging.getLogger(__name__)


def decode_base64_image(data_url):
    pattern = r'^data:(?P<mime>image/[^;]+);base64,(?P<data>.+)$'
    match = re.match(pattern, data_url)
    if not match:
        return None

    mime_type = match.group('mime')
    image_data = match.group('data')
    try:
        decoded_file = base64.b64decode(image_data)
    except (TypeError, ValueError):
        return None

    extension = mime_type.split('/')[-1]
    filename = f"field_{uuid.uuid4().hex}.{extension}"
    return ContentFile(decoded_file, name=filename)


# ============================================================================
# PUBLIC API VIEWS
# ============================================================================

@api_view(['GET'])
@permission_classes([AllowAny])
def fields_list(request):
    """
    List all approved fields for public access
    """
    fields = FieldCard.objects.filter(status=FieldStatus.APPROVED)
    serializer = FieldCardSerializer(fields, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([AllowAny])
def field_detail(request, field_id):
    """
    Get detailed information about a specific field.
    Public users may only see approved fields. Owners can also view their own fields,
    even when they are pending or rejected.
    """
    if request.user.is_authenticated:
        field = get_object_or_404(FieldCard, id=field_id)
        if field.status == FieldStatus.APPROVED or field.owner == request.user or request.user.is_staff:
            serializer = FieldCardSerializer(field, context={'request': request})
            return Response(serializer.data)
        raise Http404

    field = get_object_or_404(FieldCard, id=field_id, status=FieldStatus.APPROVED)
    serializer = FieldCardSerializer(field, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_field_rating(request, field_id):
    """
    Submit a rating for a field
    """
    try:
        field = get_object_or_404(FieldCard, id=field_id)
    except:
        return Response(
            {"detail": "Field not found"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Check if user already rated this field
    if Review.objects.filter(field=field, user=request.user).exists():
        return Response(
            {"detail": "You have already rated this field"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    rating = request.data.get('rating')
    comment = request.data.get('comment', '')
    
    if not rating:
        return Response(
            {"detail": "Rating is required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        rating_int = int(rating)
    except (ValueError, TypeError):
        return Response(
            {"detail": "Rating must be a number"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not (1 <= rating_int <= 5):
        return Response(
            {"detail": "Rating must be between 1 and 5"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        Review.objects.create(
            field=field,
            user=request.user,
            rating=rating_int,
            comment=comment or ''
        )
    except Exception as e:
        logger.error(f"Error creating review: {e}", exc_info=True)
        return Response(
            {"detail": f"Error creating review: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    return Response(
        {"detail": "Rating submitted successfully", "userHasReviewed": True},
        status=status.HTTP_201_CREATED
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def bookings_for_user(request, user_id):
    """
    Get bookings for a specific user
    """
    if request.user.id != user_id:
        return Response(
            {"detail": "You can only view your own bookings"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    bookings = Booking.objects.filter(user_id=user_id).select_related('field').order_by('-created_at')
    serializer = BookingSerializer(bookings, many=True, context={'request': request})
    return Response(serializer.data)


# ============================================================================
# AUTH VIEWS
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_user(request):
    """
    Get current user information
    """
    from .serializers import UserWithProfileSerializer
    serializer = UserWithProfileSerializer(request.user)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_profile(request):
    """
    Complete user profile
    """
    user = request.user
    profile = user.profile
    
    first_name = request.data.get('first_name')
    last_name = request.data.get('last_name')
    email = request.data.get('email')
    age = request.data.get('age')
    user_type = request.data.get('user_type')
    
    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name
    if email is not None:
        user.email = email
    if age is not None:
        profile.age = age
    if user_type:
        profile.user_type = user_type
    
    user.save()
    profile.save()
    
    from .serializers import UserWithProfileSerializer
    serializer = UserWithProfileSerializer(user)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([AllowAny])
def request_otp(request):
    """
    Request OTP for phone authentication
    """
    from django.utils import timezone
    from datetime import timedelta
    from django.contrib.auth.hashers import make_password
    import random
    from ..services import EskizSMSService
    
    phone = request.data.get('phone', '').strip()
    email = request.data.get('email', '').strip()

    if not phone and not email:
        return Response(
            {"detail": "Phone or email required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    identifier = phone or email

    if phone:
        # Validate phone format (basic check)
        if not phone.startswith('+998') or len(phone) != 13:
            return Response(
                {"detail": "Invalid phone format. Use +998XXXXXXXXX"},
                status=status.HTTP_400_BAD_REQUEST
            )

    if email and not phone:
        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"detail": "Invalid email address."},
                status=status.HTTP_400_BAD_REQUEST
            )

    # If this OTP request is for a profile phone update, ensure the number is not already registered to another user.
    purpose = request.data.get('purpose')
    if purpose == 'phone_update':
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required for phone update."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        if not phone:
            return Response(
                {"detail": "Phone update requires a phone number."},
                status=status.HTTP_400_BAD_REQUEST
            )
        existing_profile = UserProfile.objects.filter(phone=phone).exclude(user=request.user).exists()
        if existing_profile:
            return Response(
                {"detail": "This phone number is already registered."},
                status=status.HTTP_400_BAD_REQUEST
            )

    # Check rate limiting
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    host = request.get_host()
    now = timezone.now()
    rate_limit_window = timedelta(minutes=5)
    local_dev_request = (
        settings.DEBUG
        or getattr(settings, 'OTP_ALLOW_MISSING_SMS_PROVIDER', False)
        or ip.startswith('127.')
        or ip == '::1'
        or host.startswith('localhost')
        or host.startswith('127.0.0.1')
    )
    max_requests = 9999 if local_dev_request else 3
    window_cutoff = now - rate_limit_window
    bucket_start = now.replace(second=0, microsecond=0)

    recent_requests = OTPRateLimit.objects.filter(
        phone=identifier,
        ip_address=ip,
        window_start__gte=window_cutoff
    ).aggregate(total=Sum('request_count'))['total'] or 0

    if recent_requests >= max_requests:
        retry_after = int((rate_limit_window - (now - window_cutoff)).total_seconds())
        response = Response(
            {"detail": "Too many OTP requests. Please wait a moment and try again."},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
        response['Retry-After'] = retry_after
        return response

    # Track this request in current time bucket
    otp_rate_limit, created = OTPRateLimit.objects.get_or_create(
        phone=identifier,
        ip_address=ip,
        window_start=bucket_start,
        defaults={"request_count": 1}
    )
    if not created:
        otp_rate_limit.request_count += 1
        otp_rate_limit.save(update_fields=["request_count"])
    
    # Generate OTP
    code = f"{random.randint(0, 999999):06d}"
    code_hash = make_password(code)
    
    # Save to database
    expires_at = now + timedelta(minutes=3)
    otp_obj = OTPCode.objects.create(
        phone=identifier,
        code_hash=code_hash,
        expires_at=expires_at
    )

    # Send OTP by SMS or email
    if email and not phone:
        try:
            subject = "ArenaGo: Your verification code"
            message_body = f"Salom! ArenaGo uchun tasdiqlash kodi: {code}. Kod 3 daqiqa davomida amal qiladi."
            send_mail(
                subject,
                message_body,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            logger.info(f"OTP email sent to {email}, ID: {otp_obj.id}")
            return Response({"detail": "OTP sent successfully"})
        except Exception as e:
            logger.error(f"Failed to send OTP email to {email}: {e}", exc_info=True)
            if local_dev_request:
                logger.info(f"Local dev fallback after email send failure for {email}: {e}")
                print(f"DEBUG/local fallback OTP for {identifier}: {code}")
                return Response({
                    "detail": "OTP sent successfully (local fallback). Check server logs for the code.",
                    "debug_code": code,
                })
            return Response(
                {"detail": "Error sending OTP via email provider"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

    try:
        sms_service = EskizSMSService()
    except ValueError as e:
        logger.warning(f"SMS service configuration error: {e}")
        remote_addr = request.META.get('REMOTE_ADDR', '')
        allow_missing_sms = (
            settings.DEBUG
            or getattr(settings, 'OTP_ALLOW_MISSING_SMS_PROVIDER', False)
            or remote_addr.startswith('127.')
            or remote_addr == '::1'
            or request.get_host().startswith('localhost')
            or request.get_host().startswith('127.0.0.1')
        )
        if allow_missing_sms:
            logger.info(f"DEBUG/local fallback OTP for {identifier}: {code}")
            print(f"DEBUG/local fallback OTP for {identifier}: {code}")
            return Response({
                "detail": "OTP sent successfully (DEBUG/local fallback). Check server logs for the code.",
                "debug_code": code,
            })
        return Response(
            {"detail": "SMS provider is not configured. Set ESKIZ_EMAIL and ESKIZ_PASSWORD."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    try:
        message = f"ArenaGo: Your verification code is {code}. Valid for 3 minutes."
        result = sms_service.send_sms(phone, message)
        
        if result[0]:
            logger.info(f"OTP sent to {phone}, ID: {otp_obj.id}")
            return Response({"detail": "OTP sent successfully"})
        else:
            error_message = result[1] if result[1] else "Failed to send SMS"
            logger.error(f"Failed to send OTP to {phone}: {error_message}")
            if local_dev_request:
                logger.info(f"Local dev fallback after SMS send failure for {phone}: {error_message}")
                print(f"DEBUG/local fallback OTP for {identifier}: {code}")
                return Response({
                    "detail": "OTP sent successfully (local fallback). Check server logs for the code.",
                    "debug_code": code,
                })
            return Response(
                {"detail": error_message},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
    except Exception as e:
        logger.error(f"Error sending OTP: {e}", exc_info=True)
        if local_dev_request:
            logger.info(f"Local dev fallback after send exception for {phone}: {e}")
            print(f"DEBUG/local fallback OTP for {identifier}: {code}")
            return Response({
                "detail": "OTP sent successfully (local fallback). Check server logs for the code.",
                "debug_code": code,
            })
        return Response(
            {"detail": "Error sending OTP via SMS provider"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def auth_verify_code(request):
    """
    Verify OTP code and authenticate user
    """
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.tokens import RefreshToken
    
    phone = request.data.get('phone', '').strip()
    email = request.data.get('email', '').strip()
    code = request.data.get('code', '').strip()
    identifier = phone or email

    if not identifier or not code:
        return Response(
            {"detail": "Phone or email and code required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Find the most recent unused OTP for this identifier
    from django.utils import timezone
    otp_obj = OTPCode.objects.filter(
        phone=identifier,
        is_used=False,
        expires_at__gt=timezone.now()
    ).order_by('-created_at').first()
    
    if not otp_obj:
        return Response(
            {"detail": "No valid OTP found"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verify the code
    if not otp_obj.verify_code(code):
        return Response(
            {"detail": "Invalid or expired code"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Mark OTP as used
    otp_obj.is_used = True
    otp_obj.save(update_fields=['is_used'])
    
# Get or create user. Do not persist a fake temp email if none was provided.
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=identifier,
        defaults={'email': email if email else ''}
    )

    if email and user.email != email:
        user.email = email
        user.save(update_fields=['email'])

    if user.email and user.email.endswith('@temp.com'):
        user.email = ''
        user.save(update_fields=['email'])
    
    # Create profile if new user or update placeholder phone if needed
    from ..models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={'phone': identifier}
    )
    if profile.phone.startswith('auto-') and identifier:
        profile.phone = identifier
        profile.save(update_fields=['phone'])

    if email and created:
        try:
            subject = "ArenaGo: Welcome!"
            body = f"Salom! ArenaGo ga xush kelibsiz. Siz endi ArenaGo bilan maydonlar bron qilishingiz mumkin."
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as e:
            logger.warning(f"Failed to send welcome email to {email}: {e}", exc_info=True)
    
    # Generate tokens
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token
    
    from .serializers import UserWithProfileSerializer
    serializer = UserWithProfileSerializer(user)

    return Response({
        'access': str(access),
        'refresh': str(refresh),
        'user': serializer.data,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def auth_login(request):
    """
    Login with phone and OTP
    """
    return auth_verify_code(request)


@api_view(['GET'])
@permission_classes([AllowAny])
def ticket_shop_config(request):
    """
    Get ticket shop configuration
    """
    from ..models import TicketConfig, TicketItem
    config = TicketConfig.objects.first()
    if not config:
        return Response({"tickets": []})
    
    type_to_id = {
        'discount_10': 'ten',
        'discount_20': 'twenty',
        'discount_50': 'fifty',
        'free_field': 'free',
    }

    items = TicketItem.objects.filter(config=config)
    data = {
        "tickets": [
            {
                "id": type_to_id.get(item.type, item.type),
                "price_coins": item.price_coins,
            } for item in items
        ]
    }
    return Response(data)


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_detail(request, user_id):
    """
    Get or update user details.
    """
    if request.user.id != user_id:
        return Response(
            {"detail": "You can only view your own details"},
            status=status.HTTP_403_FORBIDDEN
        )

    if request.method in ['PUT', 'PATCH']:
        user = request.user
        profile = getattr(user, 'profile', None)

        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        email = request.data.get('email')
        phone = request.data.get('phone')
        age = request.data.get('age')

        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if email is not None:
            user.email = email
        if profile:
            if phone is not None:
                if phone and UserProfile.objects.filter(phone=phone).exclude(user=user).exists():
                    return Response(
                        {"detail": "This phone number is already registered."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                profile.phone = phone
            if age is not None:
                profile.age = age

        user.save()
        if profile:
            profile.save()

        from .serializers import UserWithProfileSerializer
        serializer = UserWithProfileSerializer(user)
        return Response(serializer.data)

    from .serializers import UserWithProfileSerializer
    serializer = UserWithProfileSerializer(request.user)
    return Response(serializer.data)


# ============================================================================
# OWNER API VIEWS
# ============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def owner_fields(request, owner_id):
    """
    Get or create fields for a specific owner
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"detail": "Only the owner can view or create fields"},
            status=status.HTTP_403_FORBIDDEN
        )

    if request.method == 'GET':
        fields = FieldCard.objects.filter(owner_id=owner_id)
        serializer = FieldCardSerializer(fields, many=True, context={'request': request})
        return Response(serializer.data)

    # POST: create a new owner field
    data = request.data.copy()
    logger.info(f"Field creation request data: {data}")
    
    if 'location' in data and 'city' not in data:
        data['city'] = data.pop('location')
    if 'pricePerHour' in data and 'price_per_hour' not in data:
        data['price_per_hour'] = data.pop('pricePerHour')
    if 'length' in data and 'length_m' not in data:
        raw_length = data.pop('length')
        data['length_m'] = int(float(raw_length)) if raw_length not in (None, '') else None
    if 'width' in data and 'width_m' not in data:
        raw_width = data.pop('width')
        data['width_m'] = int(float(raw_width)) if raw_width not in (None, '') else None

    logger.info(f"Normalized field data: {data}")

    serializer = FieldCardCreateSerializer(data=data)
    if not serializer.is_valid():
        logger.error(f"Serializer validation failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    validated = serializer.validated_data
    logger.info(f"Validated data: {validated}")
    
    image_value = validated.get('image', '')
    if isinstance(image_value, str) and image_value.startswith('data:'):
        image_value = decode_base64_image(image_value)

    field = FieldCard.objects.create(
        owner=request.user,
        name=validated['name'],
        city=validated['city'],
        district=validated['district'],
        address=validated['address'],
        description=validated.get('description', ''),
        price_per_hour=validated['price_per_hour'],
        image=image_value or '',
        length_m=validated.get('length_m'),
        width_m=validated.get('width_m'),
        status=FieldStatus.PENDING,
    )

    for image_value in validated.get('images', []):
        if isinstance(image_value, str) and image_value.startswith('data:'):
            image_file = decode_base64_image(image_value)
        else:
            image_file = None
        if image_file:
            FieldImage.objects.create(field=field, image=image_file)

    for amenity_name in validated.get('amenities', []):
        if not amenity_name:
            continue
        amenity, _ = Amenity.objects.get_or_create(name=amenity_name)
        field.amenities.add(amenity)

    logger.info(f"Field created successfully: {field.id}")
    return Response(FieldCardSerializer(field, context={'request': request}).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def owner_field_detail(request, owner_id, field_id):
    """
    Get, update, or delete detailed field info for owner
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"detail": "Only the owner can view, update, or delete their fields"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    field = get_object_or_404(FieldCard, id=field_id, owner_id=owner_id)

    if request.method == 'GET':
        serializer = FieldCardSerializer(field, context={'request': request})
        return Response(serializer.data)

    if request.method == 'PUT':
        # Update field
        data = request.data.copy()
        if 'location' in data and 'city' not in data:
            data['city'] = data.pop('location')
        if 'pricePerHour' in data and 'price_per_hour' not in data:
            data['price_per_hour'] = data.pop('pricePerHour')
        if 'length' in data and 'length_m' not in data:
            raw_length = data.pop('length')
            data['length_m'] = int(float(raw_length)) if raw_length not in (None, '') else None
        if 'width' in data and 'width_m' not in data:
            raw_width = data.pop('width')
            data['width_m'] = int(float(raw_width)) if raw_width not in (None, '') else None

        serializer = FieldCardCreateSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        field.name = validated.get('name', field.name)
        field.city = validated.get('city', field.city)
        field.district = validated.get('district', field.district)
        field.address = validated.get('address', field.address)
        field.description = validated.get('description', field.description)
        field.price_per_hour = validated.get('price_per_hour', field.price_per_hour)
        image_value = validated.get('image')
        if isinstance(image_value, str) and image_value.startswith('data:'):
            image_value = decode_base64_image(image_value)
        if image_value:
            field.image = image_value

        for image_value in validated.get('images', []):
            if isinstance(image_value, str) and image_value.startswith('data:'):
                image_file = decode_base64_image(image_value)
            else:
                image_file = None
            if image_file:
                FieldImage.objects.create(field=field, image=image_file)

        if validated.get('length_m') is not None:
            field.length_m = validated['length_m']
        if validated.get('width_m') is not None:
            field.width_m = validated['width_m']
        
        field.save()
        
        # Update amenities if provided
        amenities = validated.get('amenities', [])
        if amenities:
            field.amenities.clear()
            for amenity_name in amenities:
                if amenity_name:
                    amenity, _ = Amenity.objects.get_or_create(name=amenity_name)
                    field.amenities.add(amenity)

        return Response(FieldCardSerializer(field, context={'request': request}).data)

    if request.method == 'DELETE':
        field.delete()
        return Response({"detail": "Field deleted successfully"}, status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_bookings_api(request, owner_id):
    """
    Get bookings for owner's fields
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"detail": "Only the owner can view their bookings"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    bookings = Booking.objects.filter(field__owner_id=owner_id).select_related('field', 'user').order_by('-created_at')
    serializer = BookingSerializer(bookings, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_booking(request, owner_id, booking_id):
    """
    Verify booking completion
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"ok": False, "error": "Only the owner can verify bookings"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    booking = get_object_or_404(
        Booking.objects.select_related('field'),
        id=booking_id,
        field__owner_id=owner_id
    )
    
    if booking.status == BookingStatus.VERIFIED:
        return Response(
            {"ok": False, "error": "Bu buyurtma allaqachon tasdiqlangan"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    code = request.data.get('code') or request.data.get('verificationCode')
    if not code:
        return Response(
            {"ok": False, "error": "Verification code required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if booking.verification_code == code:
        booking.status = BookingStatus.VERIFIED
        booking.save(update_fields=['status'])
        return Response({"ok": True, "status": booking.status})
    else:
        return Response(
            {"ok": False, "error": "Invalid verification code"},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_stats(request, owner_id):
    """
    Get owner statistics
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"detail": "Only the owner can view their stats"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Simple stats - can be expanded
    fields_count = FieldCard.objects.filter(owner_id=owner_id).count()
    bookings_count = Booking.objects.filter(field__owner_id=owner_id).count()
    
    return Response({
        "fields_count": fields_count,
        "bookings_count": bookings_count
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def promote_field(request, owner_id, field_id):
    """
    Promote a field (placeholder)
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"detail": "Only the owner can promote fields"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    field = get_object_or_404(FieldCard, id=field_id, owner_id=owner_id)
    # Placeholder - implement promotion logic
    return Response({"detail": "Field promotion not implemented yet"})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_card(request, owner_id):
    """
    Get owner card info
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"detail": "Only the owner can view their card"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Placeholder
    return Response({"detail": "Owner card not implemented yet"})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_wallet(request, owner_id):
    """
    Get owner wallet info
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"detail": "Only the owner can view their wallet"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Placeholder
    return Response({"balance": 0})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def owner_withdraw(request, owner_id):
    """
    Withdraw funds
    """
    if request.user.id != owner_id or not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.OWNER:
        return Response(
            {"detail": "Only the owner can withdraw"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Placeholder
    return Response({"detail": "Withdrawal not implemented yet"})


# ============================================================================
# AGENT API VIEWS
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_tickets_list(request):
    """
    Get support tickets for agent
    """
    if not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.AGENT:
        return Response(
            {"detail": "Only support agents can view tickets"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    from ..models import SupportTicket
    tickets = SupportTicket.objects.all().order_by('-created_at')
    # Simple response - can be expanded
    data = [
        {
            "id": ticket.id,
            "subject": ticket.subject,
            "status": ticket.status,
            "created_at": ticket.created_at
        } for ticket in tickets
    ]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_ticket_detail(request, ticket_id):
    """
    Get ticket details for agent
    """
    if not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.AGENT:
        return Response(
            {"detail": "Only support agents can view tickets"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    from ..models import SupportTicket
    ticket = get_object_or_404(SupportTicket, id=ticket_id)
    # Simple response - can be expanded
    return Response({
        "id": ticket.id,
        "subject": ticket.subject,
        "message": ticket.message,
        "status": ticket.status,
        "created_at": ticket.created_at
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def agent_ticket_reply(request, ticket_id):
    """
    Reply to a ticket
    """
    if not hasattr(request.user, 'profile') or request.user.profile.user_type != UserType.AGENT:
        return Response(
            {"detail": "Only support agents can reply to tickets"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Placeholder
    return Response({"detail": "Reply functionality not implemented yet"})


# ============================================================================
# USER SUPPORT VIEWS
# ============================================================================

def _get_user_conversation(request):
    """
    Return the current user's support conversation.
    """
    from .serializers import SupportConversationSerializer
    from ..models import SupportTicket

    ticket = SupportTicket.objects.filter(user=request.user).order_by('-created_at').first()
    if not ticket:
        return Response({"messages": []})

    serializer = SupportConversationSerializer(ticket)
    return Response(serializer.data)


def _post_user_support_message(request):
    """
    Persist a support message from the authenticated user.
    """
    from .serializers import SupportMessageCreateSerializer, SupportMessageSerializer
    from ..models import SupportTicket, SupportMessage

    serializer = SupportMessageCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    message_text = serializer.validated_data['message']
    profile = getattr(request.user, 'profile', None)
    phone = getattr(profile, 'phone', '') if profile else ''

    ticket, _ = SupportTicket.objects.get_or_create(
        user=request.user,
        defaults={'phone': phone}
    )

    message = SupportMessage.objects.create(
        ticket=ticket,
        sender=SupportMessage.SENDER_USER,
        content=message_text,
    )

    response_serializer = SupportMessageSerializer(message)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_conversation(request):
    return _get_user_conversation(request)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def user_send_message(request):
    return _post_user_support_message(request)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def user_support_messages(request):
    """
    Handle user support messages for the legacy frontend route.
    """
    if request.method == 'GET':
        return _get_user_conversation(request)
    return _post_user_support_message(request)


@api_view(['GET'])
@permission_classes([AllowAny])
def support_info(request):
    """
    Get support info
    """
    return Response({
        "support_email": "support@arenago.com",
        "support_phone": "+998901234567"
    })


# ============================================================================
# SERIALIZERS FOR INPUT VALIDATION
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def owner_create_field(request):
    """
    Create a new field (owner only)
    
    ✅ SECURITY:
    - No @csrf_exempt - CSRF protection active
    - Validates user is authenticated
    - Validates input using Serializer
    - Proper error responses
    """
    if request.method != "POST":
        return Response(
            {"detail": "Method not allowed"},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    # Check if user is field owner
    if not hasattr(request.user, "profile") or request.user.profile.user_type != "OWNER":
        return Response(
            {"detail": "Only owners can add fields"},
            status=status.HTTP_403_FORBIDDEN
        )

    # Validate input using Serializer
    serializer = FieldCardCreateSerializer(data=request.data)
    if not serializer.is_valid():
        logger.warning(f"Invalid field creation data from {request.user.id}: {serializer.errors}")
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    # Create field with validated data
    try:
        field = FieldCard.objects.create(
            owner=request.user,
            name=serializer.validated_data['name'],
            city=serializer.validated_data['city'],
            district=serializer.validated_data['district'],
            address=serializer.validated_data['address'],
            description=serializer.validated_data.get('description', ''),
            price_per_hour=serializer.validated_data['price_per_hour'],
            status=FieldStatus.PENDING,
        )
        logger.info(f"Field created: {field.id} by owner {request.user.id}")
        return Response(
            FieldCardSerializer(field).data,
            status=status.HTTP_201_CREATED
        )
    except Exception as e:
        logger.error(f"Error creating field: {e}", exc_info=True)
        return Response(
            {"detail": "Error creating field"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_booking(request):
    """
    Create a booking with proper validation
    
    ✅ SECURITY:
    - No @csrf_exempt - CSRF protection active
    - Validates all input fields
    - Checks date range (no past dates, max 90 days ahead)
    - Validates field exists and is approved
    - Uses database transactions
    """
    serializer = BookingCreateSerializer(data=request.data)
    if not serializer.is_valid():
        logger.warning(f"Invalid booking data from {request.user.id}: {serializer.errors}")
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    field_id = serializer.validated_data['field_id']
    booking_date = serializer.validated_data['date']
    start_time_str = serializer.validated_data.get('start_time')
    duration_hours = serializer.validated_data.get('duration_hours', 1)
    ticket = serializer.validated_data.get('ticket')

    # Validate date is in future
    today = date.today()
    if booking_date < today:
        return Response(
            {"detail": "Cannot book past dates"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if booking_date > today + timedelta(days=90):
        return Response(
            {"detail": "Cannot book more than 90 days ahead"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate duration
    if not (1 <= duration_hours <= 8):
        return Response(
            {"detail": "Duration must be between 1 and 8 hours"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Fetch field and verify status
    field = get_object_or_404(FieldCard, id=field_id, status=FieldStatus.APPROVED)

    if isinstance(start_time_str, time):
        start_time = start_time_str
    else:
        try:
            start_time = datetime.strptime(start_time_str, "%H:%M").time()
        except (TypeError, ValueError):
            logger.warning(f"Invalid booking start_time from {request.user.id}: {start_time_str}")
            return Response(
                {"detail": "Invalid start_time format, expected HH:MM"},
                status=status.HTTP_400_BAD_REQUEST
            )

    # Prevent overlapping bookings on the same field and date
    requested_start = datetime.combine(date.min, start_time)
    requested_end = requested_start + timedelta(hours=duration_hours)
    existing_bookings = Booking.objects.filter(field=field, date=booking_date).exclude(status=BookingStatus.CANCELLED)

    for existing in existing_bookings:
        existing_start = datetime.combine(date.min, existing.start_time)
        existing_end = existing_start + timedelta(hours=existing.duration_hours)
        if requested_start < existing_end and existing_start < requested_end:
            logger.info(
                f"Booking conflict for user {request.user.id} on field {field.id} {booking_date} {start_time_str}"
            )
            return Response(
                {"detail": "Selected time slot is already booked or overlaps an existing booking."},
                status=status.HTTP_409_CONFLICT
            )

    try:
        with transaction.atomic():
            booking = Booking.objects.create(
                field=field,
                user=request.user,
                date=booking_date,
                start_time=start_time,
                duration_hours=duration_hours,
                ticket_used=ticket,
                status=BookingStatus.WAITING_PAYMENT,
            )
            logger.info(f"Booking created: {booking.id} by user {request.user.id}")
            serializer = BookingSerializer(booking, context={'request': request})
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED
            )
    except IntegrityError as e:
        logger.warning(f"Booking IntegrityError for user {request.user.id}: {e}", exc_info=True)
        return Response(
            {"detail": "Selected time slot is already booked."},
            status=status.HTTP_409_CONFLICT
        )
    except Exception as e:
        logger.error(f"Error creating booking: {e}", exc_info=True)
        return Response(
            {"detail": "Error creating booking"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_booking_code(request, booking_id):
    """
    Verify booking completion code
    
    ✅ SECURITY:
    - No @csrf_exempt - CSRF protection active
    - Validates code input (alphanumeric only)
    - Uses get_object_or_404 for authorization
    - Prevents timing attacks with constant-time comparison
    """
    # Validate code input
    code = (request.data.get('code') or request.data.get('verificationCode') or '').strip()
    
    if not code:
        return Response(
            {"detail": "Verification code required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate code format (3 alphanumeric characters)
    if not (len(code) == 3 and code.isalnum()):
        return Response(
            {"detail": "Invalid code format"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        booking = get_object_or_404(
            Booking.objects.select_related("field"),
            id=booking_id,
            field__owner=request.user  # Authorization check
        )

        if booking.status == BookingStatus.VERIFIED:
            return Response(
                {"ok": False, "error": "Bu buyurtma allaqachon tasdiqlangan"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Use constant-time comparison to prevent timing attacks
        import secrets
        if secrets.compare_digest(booking.verification_code, code):
            booking.status = BookingStatus.VERIFIED
            booking.save(update_fields=["status"])
            logger.info(f"Booking {booking_id} verified by owner {request.user.id}")
            return Response(
                {"ok": True, "status": booking.status},
                status=status.HTTP_200_OK
            )

        logger.warning(f"Invalid code attempt for booking {booking_id}")
        return Response(
            {"ok": False, "error": "Invalid code"},
            status=status.HTTP_400_BAD_REQUEST
        )

    except Exception as e:
        logger.error(f"Error verifying booking: {e}", exc_info=True)
        return Response(
            {"detail": "Error verifying booking"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================================================
# SERIALIZERS FOR INPUT VALIDATION
# ============================================================================

from rest_framework import serializers
from django.core.validators import MinValueValidator, MaxValueValidator

class FieldCardCreateSerializer(serializers.Serializer):
    """Validate field creation/update input - all fields optional for partial updates"""
    name = serializers.CharField(
        max_length=100,
        min_length=3,
        required=False,
        allow_blank=False
    )
    city = serializers.CharField(
        max_length=100,
        min_length=2,
        required=False,
        allow_blank=False
    )
    district = serializers.CharField(
        max_length=200,
        min_length=2,
        required=False,
        allow_blank=False
    )
    address = serializers.CharField(
        max_length=255,
        min_length=5,
        required=False,
        allow_blank=False
    )
    description = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True
    )
    price_per_hour = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1000,  # 1000 som minimum
        max_value=1000000  # 1M som maximum
    )
    image = serializers.CharField(required=False, allow_blank=True)
    images = serializers.ListField(
        child=serializers.CharField(required=False, allow_blank=True),
        required=False,
        allow_empty=True
    )
    length_m = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    width_m = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    amenities = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        allow_empty=True
    )

    def validate_name(self, value):
        if value and not value.replace(" ", "").isalnum():
            raise serializers.ValidationError("Name contains invalid characters")
        return value


class BookingCreateSerializer(serializers.Serializer):
    """Validate booking creation input"""
    field_id = serializers.IntegerField(required=True, min_value=1)
    date = serializers.DateField(required=True, format='%Y-%m-%d')
    start_time = serializers.TimeField(required=False, format='%H:%M')
    duration_hours = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=8
    )
    slot_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False
    )
    ticket = serializers.ChoiceField(
        choices=[('ten', '10%'), ('twenty', '20%'), ('fifty', '50%'), ('free', '100%')],
        required=False,
        allow_null=True,
        default=None
    )

    def validate(self, data):
        # Must have either time+duration or slot_ids
        if not data.get('slot_ids'):
            if not data.get('start_time') or not data.get('duration_hours'):
                raise serializers.ValidationError(
                    "Must provide either slot_ids or (start_time + duration_hours)"
                )
        return data
