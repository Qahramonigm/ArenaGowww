"""
Payment System API Serializers and Endpoints
DRF-based REST API for booking and payment flow
"""
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Sum, Count, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, date, timedelta
import logging

from .payment_models import (
    Commission, OwnerWallet, PlatformBalance, BookingStatus
)
from .models import Booking, Payment, FieldCard, PaymentStatus
from .payment_gateway import (
    PaymentProcessor, ClickPaymentGateway, PaymePaymentGateway,
    PaymentGatewayError, SignatureVerificationError
)

logger = logging.getLogger(__name__)


# ============================================================================
# SERIALIZERS
# ============================================================================

class FieldCardSimpleSerializer(serializers.ModelSerializer):
    """Minimal field info for booking responses"""
    class Meta:
        model = FieldCard
        fields = ['id', 'name', 'city', 'price_per_hour']


class BookingCreateSerializer(serializers.Serializer):
    """Create booking request"""
    field_id = serializers.IntegerField(required=True, min_value=1)
    date = serializers.DateField(required=True, format='%Y-%m-%d')
    start_time = serializers.TimeField(required=True, format='%H:%M')
    duration_hours = serializers.IntegerField(required=True, min_value=1, max_value=8)
    
    def validate_date(self, value):
        """Date must be today or in future"""
        if value < date.today():
            raise serializers.ValidationError("Cannot book past dates")
        if value > date.today() + timedelta(days=90):
            raise serializers.ValidationError("Cannot book more than 90 days ahead")
        return value
    
    def validate_field_id(self, value):
        """Field must exist"""
        if not FieldCard.objects.filter(id=value).exists():
            raise serializers.ValidationError("Field not found")
        return value


class BookingDetailSerializer(serializers.ModelSerializer):
    """Full booking details"""
    field = FieldCardSimpleSerializer(read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    owner_name = serializers.CharField(source='field.owner.get_full_name', read_only=True)
    
    class Meta:
        model = Booking
        fields = [
            'id', 'field', 'date', 'start_time', 'duration_hours',
            'subtotal', 'service_fee', 'total_price',
            'booking_status', 'user_name', 'owner_name',
            'created_at', 'verified_at'
        ]
        read_only_fields = ['subtotal', 'total_price', 'booking_status']


class PaymentInitiateSerializer(serializers.Serializer):
    """Initiate payment request"""
    booking_id = serializers.IntegerField(required=True, min_value=1)
    gateway = serializers.ChoiceField(choices=['click', 'payme'], required=True)


class PaymentStatusSerializer(serializers.ModelSerializer):
    """Payment status response"""
    class Meta:
        model = Payment
        fields = [
            'id', 'booking', 'status', 'amount',
            'gateway', 'paid_at', 'created_at'
        ]


class CommissionSerializer(serializers.ModelSerializer):
    """Owner commission details"""
    field_name = serializers.CharField(source='booking.field.name', read_only=True)
    booking_date = serializers.DateField(source='booking.date', read_only=True)
    
    class Meta:
        model = Commission
        fields = [
            'id', 'field_name', 'booking_date',
            'booking_price', 'service_fee', 'owner_share', 'paid_to_owner',
            'created_at'
        ]


class OwnerWalletSerializer(serializers.ModelSerializer):
    """Owner wallet details"""
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    
    class Meta:
        model = OwnerWallet
        fields = [
            'balance', 'total_earned', 'total_withdrawn',
            'total_refunded', 'owner_name', 'last_payout_at'
        ]


# ============================================================================
# API ENDPOINTS
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_booking(request):
    """
    Create a booking
    
    POST /api/bookings/create/
    {
        "field_id": 1,
        "date": "2026-04-15",
        "start_time": "18:00",
        "duration_hours": 2
    }
    
    Response:
    {
        "id": 123,
        "field": {"id": 1, "name": "Green Field", "price_per_hour": 100000},
        "date": "2026-04-15",
        "start_time": "18:00",
        "duration_hours": 2,
        "subtotal": 200000,
        "service_fee": 5000,
        "total_price": 205000,
        "booking_status": "pending_payment"
    }
    """
    serializer = BookingCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    field_id = serializer.validated_data['field_id']
    booking_date = serializer.validated_data['date']
    start_time = serializer.validated_data['start_time']
    duration_hours = serializer.validated_data['duration_hours']
    
    field = get_object_or_404(FieldCard, id=field_id)
    
    try:
        with transaction.atomic():
            # Check for slot conflicts
            conflicting = Booking.objects.filter(
                field=field,
                date=booking_date,
                start_time=start_time,
                booking_status__in=[BookingStatus.CONFIRMED, BookingStatus.COMPLETED]
            ).exists()
            
            if conflicting:
                return Response(
                    {"error": "Time slot already booked"},
                    status=status.HTTP_409_CONFLICT
                )
            
            # Create booking
            booking = Booking(
                user=request.user,
                field=field,
                date=booking_date,
                start_time=start_time,
                duration_hours=duration_hours,
                booking_status=BookingStatus.PENDING_PAYMENT
            )
            booking.calculate_prices()
            booking.save()
            
            logger.info(f"Booking created: {booking.id} by user {request.user.id}")
            
            return Response(
                BookingDetailSerializer(booking).data,
                status=status.HTTP_201_CREATED
            )
    
    except Exception as e:
        logger.error(f"Error creating booking: {e}", exc_info=True)
        return Response(
            {"error": "Error creating booking"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initiate_payment(request):
    """
    Initiate payment for booking
    
    POST /api/payments/initiate/
    {
        "booking_id": 123,
        "gateway": "click"
    }
    
    Response:
    {
        "payment_url": "https://click.uz/pay?invoice_id=xxx",
        "merchant_tx_id": "ARENAGO_xxx",
        "invoice_id": "xxx"
    }
    """
    serializer = PaymentInitiateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    booking_id = serializer.validated_data['booking_id']
    gateway = serializer.validated_data['gateway']
    
    # Verify user owns the booking
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    
    try:
        result = PaymentProcessor.initiate_payment(booking_id, gateway)
        return Response(result, status=status.HTTP_200_OK)
    
    except PaymentGatewayError as e:
        logger.warning(f"Payment initiation error: {e}")
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return Response(
            {"error": "Error initiating payment"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@csrf_exempt  # Payment gateways call this from their servers
@permission_classes([AllowAny])
def click_webhook(request):
    """
    Click payment gateway webhook endpoint
    
    Called by Click servers when payment is completed
    """
    try:
        data = request.data or request.POST
        
        # Handle Click callback
        success, message = ClickPaymentGateway.handle_callback(data)
        
        if success:
            return Response(
                {"status": "ok", "message": message},
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"status": "error", "message": message},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    except Exception as e:
        logger.error(f"Click webhook error: {e}", exc_info=True)
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@csrf_exempt
@permission_classes([AllowAny])
def payme_webhook(request):
    """
    Payme payment gateway webhook endpoint
    
    Called by Payme when payment status changes
    """
    try:
        data = request.data
        
        # Handle Payme callback
        success, message = PaymePaymentGateway.handle_callback(data)
        
        if success:
            return Response(
                {"result": {"status": "ok"}},
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": {"message": message}},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    except Exception as e:
        logger.error(f"Payme webhook error: {e}", exc_info=True)
        return Response(
            {"error": {"message": str(e)}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_status(request, booking_id):
    """
    Get payment status for booking
    
    GET /api/payments/{booking_id}/status/
    
    Response:
    {
        "status": "paid",
        "booking_status": "confirmed",
        "amount": 205000,
        "paid_at": "2026-03-28T14:30:00Z"
    }
    """
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    
    try:
        payment = booking.payment
        return Response(
            PaymentStatusSerializer(payment).data,
            status=status.HTTP_200_OK
        )
    except Payment.DoesNotExist:
        return Response(
            {"error": "Payment not found"},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_booking(request, booking_id):
    """
    Cancel booking and request refund
    
    POST /api/bookings/{booking_id}/cancel/
    {
        "reason": "Cannot attend"
    }
    
    Only allowed within 24 hours of payment
    """
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    
    if not booking.can_be_cancelled():
        return Response(
            {"error": "Cannot cancel less than 24 hours before booking"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        reason = request.data.get('reason', '')
        PaymentProcessor.refund_payment(booking_id, reason)
        
        return Response(
            {
                "status": "cancelled",
                "refund_amount": booking.total_price,
                "message": "Booking cancelled and refund initiated"
            },
            status=status.HTTP_200_OK
        )
    
    except PaymentGatewayError as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )


# ============================================================================
# OWNER/WALLET ENDPOINTS
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_wallet(request, owner_id):
    """
    Get owner's wallet details
    
    GET /api/owner/<owner_id>/wallet/
    """
    from django.contrib.auth.models import User

    if request.user.id != owner_id and not request.user.is_staff:
        return Response(
            {"error": "Cannot access other owner wallet"},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        owner = User.objects.get(id=owner_id)
    except User.DoesNotExist:
        return Response(
            {"error": "Owner not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    wallet = OwnerWallet.get_or_create_for_owner(owner)
    return Response(
        OwnerWalletSerializer(wallet).data,
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_commissions(request, owner_id):
    """
    Get owner's earnings/commissions
    
    GET /api/owner/commissions/?from_date=2026-03-01&to_date=2026-03-28
    
    Response:
    [
        {
            "id": 1,
            "field_name": "Green Field",
            "booking_date": "2026-03-28",
            "booking_price": 100000,
            "service_fee": 5000,
            "owner_share": 100000,
            "paid_to_owner": true,
            "created_at": "2026-03-28T10:00:00Z"
        }
    ]
    """
    from django.contrib.auth.models import User

    if request.user.id != owner_id and not request.user.is_staff:
        return Response(
            {"error": "Cannot access other owner commissions"},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        owner = User.objects.get(id=owner_id)
    except User.DoesNotExist:
        return Response(
            {"error": "Owner not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    commissions = Commission.objects.filter(owner=owner)
    
    # Filter by date range if provided
    from_date = request.query_params.get('from_date')
    to_date = request.query_params.get('to_date')
    
    if from_date:
        from_date = datetime.strptime(from_date, '%Y-%m-%d').date()
        commissions = commissions.filter(created_at__date__gte=from_date)
    
    if to_date:
        to_date = datetime.strptime(to_date, '%Y-%m-%d').date()
        commissions = commissions.filter(created_at__date__lte=to_date)
    
    serializer = CommissionSerializer(commissions, many=True)
    
    # Add summary
    return Response(
        {
            "count": commissions.count(),
            "total_earned": commissions.aggregate(
                total=Sum('owner_share')
            )['total'] or 0,
            "commissions": serializer.data
        },
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_earnings_stats(request, owner_id):
    """
    Get owner earnings stats for month
    
    GET /api/owner/<owner_id>/stats/?year=2026&month=3
    
    Response:
    {
        "earnings": 5000000,
        "totalBookings": 10,
        "average_per_booking": 500000
    }
    """
    from django.contrib.auth.models import User
    
    # Verify ownership or admin access
    if request.user.id != owner_id and not request.user.is_staff:
        return Response(
            {"error": "Cannot access other owner stats"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        owner = User.objects.get(id=owner_id)
    except User.DoesNotExist:
        return Response(
            {"error": "Owner not found"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    year = int(request.query_params.get('year', timezone.now().year))
    month = int(request.query_params.get('month', timezone.now().month))
    
    # Get verified or completed bookings (owner's actual earnings = subtotal)
    bookings = Booking.objects.filter(
        field__owner=owner,
        created_at__year=year,
        created_at__month=month,
        status__in=['verified', 'completed']  # Only paid bookings
    )
    
    total_earned = bookings.aggregate(Sum('subtotal'))['subtotal__sum'] or 0
    total_bookings = bookings.count()
    
    return Response(
        {
            "earnings": total_earned,
            "totalBookings": total_bookings,
            "average_per_booking": total_earned // total_bookings if total_bookings > 0 else 0
        },
        status=status.HTTP_200_OK
    )


# ============================================================================
# ADMIN/ANALYTICS ENDPOINTS
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def platform_analytics(request):
    """
    Platform payment analytics (admin only)
    
    GET /api/admin/analytics/?date=2026-03-28
    
    Requires admin/staff status
    """
    if not request.user.is_staff:
        return Response(
            {"error": "Admin access required"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    from_date = request.query_params.get('date')
    if from_date:
        from_date = datetime.strptime(from_date, '%Y-%m-%d').date()
    else:
        from_date = timezone.now().date()
    
    try:
        balance = PlatformBalance.objects.get(date=from_date)
    except PlatformBalance.DoesNotExist:
        PlatformBalance.update_daily_summary()
        balance = PlatformBalance.get_or_create_today()
    
    return Response(
        {
            "date": balance.date,
            "total_bookings": balance.total_bookings,
            "total_revenue": balance.total_revenue,
            "total_fees": balance.total_fees,
            "total_payouts": balance.total_payouts,
            "average_booking": balance.average_booking_price,
            "successful_payments": balance.successful_payments,
            "failed_payments": balance.failed_payments
        },
        status=status.HTTP_200_OK
    )
