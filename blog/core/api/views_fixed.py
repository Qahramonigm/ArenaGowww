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

from django.shortcuts import get_object_or_404
from django.db import transaction
from datetime import datetime, date, timedelta

from ..models import FieldCard, FieldStatus, Booking, BookingStatus, FieldSlot
from .serializers import (
    FieldCardSerializer,
    BookingSerializer,
)

logger = logging.getLogger(__name__)


# ============================================================================
# SECURED: Remove @csrf_exempt
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

    try:
        with transaction.atomic():
            booking = Booking.objects.create(
                field=field,
                user=request.user,
                date=booking_date,
                start_time=datetime.strptime(start_time_str, "%H:%M").time(),
                duration_hours=duration_hours,
                status=BookingStatus.WAITING_PAYMENT,
            )
            logger.info(f"Booking created: {booking.id} by user {request.user.id}")
            return Response(
                BookingSerializer(booking).data,
                status=status.HTTP_201_CREATED
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
    code = request.data.get('code', '').strip()
    
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
    """Validate field creation input"""
    name = serializers.CharField(
        max_length=100,
        min_length=3,
        required=True
    )
    city = serializers.CharField(
        max_length=100,
        min_length=2,
        required=True
    )
    district = serializers.CharField(
        max_length=200,
        min_length=2,
        required=True
    )
    address = serializers.CharField(
        max_length=255,
        min_length=5,
        required=True
    )
    description = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True
    )
    price_per_hour = serializers.IntegerField(
        required=True,
        min_value=1000,  # 1000 som minimum
        max_value=1000000  # 1M som maximum
    )

    def validate_name(self, value):
        if not value.replace(" ", "").isalnum():
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

    def validate(self, data):
        # Must have either time+duration or slot_ids
        if not data.get('slot_ids'):
            if not data.get('start_time') or not data.get('duration_hours'):
                raise serializers.ValidationError(
                    "Must provide either slot_ids or (start_time + duration_hours)"
                )
        return data
