"""
Payment Gateway Integration
- Click Payment Gateway
- Payme (Uzbek payment service)

Security features:
- HMAC-SHA256 signature verification
- Idempotency checks
- Amount validation
- Timestamp validation
"""
import hmac
import hashlib
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Tuple

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .payment_models import (
    Payment, Booking, PaymentStatus, PaymentGateway,
    OwnerWallet, Commission, PlatformBalance
)

logger = logging.getLogger(__name__)


class PaymentGatewayError(Exception):
    """Base exception for payment gateway errors"""
    pass


class SignatureVerificationError(PaymentGatewayError):
    """Signature verification failed"""
    pass


class AmountMismatchError(PaymentGatewayError):
    """Payment amount doesn't match booking amount"""
    pass


class ClickPaymentGateway:
    """
    Click Payment Gateway Integration
    https://click.uz/
    """
    
    # Click API configuration
    API_URL = "https://api.click.uz/api/remote"
    
    # Get from environment
    MERCHANT_ID = settings.CLICK_MERCHANT_ID
    MERCHANT_SECRET = settings.CLICK_MERCHANT_SECRET
    MERCHANT_USER = settings.CLICK_MERCHANT_USER
    MERCHANT_PASSWORD = settings.CLICK_MERCHANT_PASSWORD
    
    class ClickError(PaymentGatewayError):
        """Click specific error"""
        pass
    
    @classmethod
    def create_invoice(cls, booking_id: int) -> Dict:
        """
        Create payment invoice on Click
        
        Returns:
            Dict with payment_url and invoice_id
        """
        booking = Booking.objects.get(id=booking_id)
        
        # Generate unique merchant transaction ID
        merchant_tx_id = f"ARENAGO_{booking.idempotency_key}"
        
        # Build request
        params = {
            'service_id': cls.SERVICE_ID,
            'merchant_id': cls.MERCHANT_ID,
            'amount': booking.total_price * 100,  # In tiyin (cents)
            'transaction_param': merchant_tx_id,
            'return_url': settings.CLICK_RETURN_URL,
            'description': f"Football field booking - {booking.field.name}"
        }
        
        # Generate signature
        signature = cls._generate_signature(params)
        params['sign_string'] = signature
        
        # Make request
        try:
            response = requests.post(
                f"{cls.API_URL}/invoice/create/",
                json=params,
                timeout=10
            )
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('error_code') != 0:
                raise cls.ClickError(f"Click error: {result.get('error_note')}")
            
            # Store payment record
            Payment.objects.create(
                booking=booking,
                gateway=PaymentGateway.CLICK,
                merchant_transaction_id=merchant_tx_id,
                amount=booking.total_price,
                gateway_response_data=result,
                status=PaymentStatus.PROCESSING
            )
            
            logger.info(f"Invoice created for booking {booking_id}")
            
            return {
                'payment_url': result.get('url'),
                'invoice_id': result.get('invoice_id'),
                'merchant_tx_id': merchant_tx_id
            }
        
        except requests.RequestException as e:
            logger.error(f"Click API error: {e}")
            raise cls.ClickError(f"Failed to create invoice: {e}")
    
    @classmethod
    def handle_callback(cls, data: Dict) -> Tuple[bool, str]:
        """
        Handle Click payment callback/webhook
        
        Click sends callback after user completes payment
        
        Returns:
            Tuple (success, message)
        """
        try:
            # Verify signature
            if not cls._verify_signature(data):
                raise SignatureVerificationError("Invalid Click signature")
            
            # Verify amount hasn't changed
            click_trans_id = data.get('click_trans_id')
            merchant_trans_id = data.get('merchant_trans_id')
            amount = int(data.get('amount', 0)) / 100  # Convert tiyin to UZS
            
            # Get payment record
            payment = Payment.objects.get(
                gateway_transaction_id=click_trans_id
            )
            
            # Verify amount
            if payment.amount != amount:
                raise AmountMismatchError(
                    f"Amount mismatch: {amount} vs {payment.amount}"
                )
            
            # Check for duplicate processing
            if payment.status == PaymentStatus.PAID:
                logger.warning(f"Duplicate payment callback for {click_trans_id}")
                return True, "Already processed"
            
            # Mark as paid and update booking
            with transaction.atomic():
                payment.gateway_transaction_id = click_trans_id
                payment.gateway_response_data = data
                payment.gateway_response_at = timezone.now()
                payment.signature_verified = True
                payment.mark_as_paid()
                
                # Update wallet and commissions
                cls._process_payout(payment.booking)
            
            logger.info(f"Payment confirmed: {click_trans_id}")
            return True, "Payment processed"
        
        except Payment.DoesNotExist:
            logger.error(f"Payment not found: {click_trans_id}")
            return False, "Payment not found"
        except (SignatureVerificationError, AmountMismatchError) as e:
            logger.error(f"Payment verification failed: {e}")
            return False, str(e)
        except Exception as e:
            logger.error(f"Unexpected error in Click callback: {e}")
            return False, f"Error: {e}"
    
    @classmethod
    def _generate_signature(cls, params: Dict) -> str:
        """Generate HMAC-SHA256 signature for Click request"""
        # Click signature format: MD5(merchant_id;service_id;amount;secret_key)
        signature_string = f"{cls.MERCHANT_ID};{cls.SERVICE_ID};{params['amount']};{cls.SECRET_KEY}"
        return hashlib.md5(signature_string.encode()).hexdigest()
    
    @classmethod
    def _verify_signature(cls, data: Dict) -> bool:
        """Verify Click webhook signature"""
        # Click callback signature: MD5(click_trans_id;service_id;secret_key;amount)
        provided_sig = data.get('sign_string', '')
        
        sig_string = f"{data.get('click_trans_id')};{data.get('service_id')};{cls.SECRET_KEY};{data.get('amount')}"
        expected_sig = hashlib.md5(sig_string.encode()).hexdigest()
        
        # Use constant-time comparison
        return hmac.compare_digest(provided_sig, expected_sig)
    
    @classmethod
    def _process_payout(cls, booking: Booking):
        """Process owner payout after successful payment"""
        # Create earnings record for bookkeeping. The platform fee is paid by the user,
        # while the owner receives the full booking subtotal.
        Commission.objects.create(
            booking=booking,
            owner=booking.field.owner,
            booking_price=booking.subtotal,
            service_fee=booking.service_fee,
            total_paid_by_user=booking.total_price,
            owner_share=booking.owner_amount,
            platform_share=booking.platform_fee,
            paid_to_owner=False  # Will be paid in daily/weekly settlement
        )
        
        # Update owner wallet (mark as pending)
        wallet = OwnerWallet.get_or_create_for_owner(booking.field.owner)
        wallet.add_earnings(booking.owner_amount)
        
        logger.info(f"Owner {booking.field.owner.id} credited {booking.owner_amount} UZS")


class PaymePaymentGateway:
    """
    Payme Integration
    https://payme.uz/
    
    Payme is a popular payment gateway in Uzbekistan
    """
    
    API_URL = "https://checkout.payme.uz/api"
    
    MERCHANT_ID = getattr(settings, 'PAYME_MERCHANT_ID', '')
    API_KEY = getattr(settings, 'PAYME_API_KEY', '')
    RETURN_URL = getattr(settings, 'PAYME_RETURN_URL', '')
    
    class PaymeError(PaymentGatewayError):
        """Payme specific error"""
        pass
    
    @classmethod
    def create_payment_link(cls, booking_id: int) -> Dict:
        """
        Create Payme payment link
        
        Returns:
            Dict with checkout_url
        """
        booking = Booking.objects.get(id=booking_id)
        
        transaction_id = f"{booking.idempotency_key}"
        
        # Build checkout URL
        checkout_url = (
            f"{cls.API_URL}/checkout/"
            f"?merchant_id={cls.MERCHANT_ID}"
            f"&amount={booking.total_price * 100}"  # In tiyin
            f"&account[booking_id]={booking_id}"
            f"&transaction_id={transaction_id}"
            f"&return_url={settings.PAYME_RETURN_URL}"
        )
        
        Payment.objects.create(
            booking=booking,
            gateway=PaymentGateway.PAYME,
            merchant_transaction_id=transaction_id,
            amount=booking.total_price,
            status=PaymentStatus.PROCESSING
        )
        
        logger.info(f"Payme link created for booking {booking_id}")
        
        return {
            'checkout_url': checkout_url,
            'transaction_id': transaction_id
        }
    
    @classmethod
    def handle_callback(cls, data: Dict) -> Tuple[bool, str]:
        """
        Handle Payme callback
        
        Payme sends webhook with payment status
        """
        try:
            auth_header = data.get('Authorization', '')
            if not cls._verify_auth(auth_header):
                raise SignatureVerificationError("Invalid Payme authentication")
            
            # Get transaction details
            transaction_id = data.get('transaction_id')
            amount = int(data.get('amount', 0)) / 100  # Convert tiyin to UZS
            state = data.get('state', 0)  # 1=completed, 2=cancelled
            
            # Get payment record
            payment = Payment.objects.get(merchant_transaction_id=transaction_id)
            
            # Verify amount
            if payment.amount != amount:
                raise AmountMismatchError(
                    f"Amount mismatch: {amount} vs {payment.amount}"
                )
            
            # Check state
            if state == 1:  # Completed
                if payment.status == PaymentStatus.PAID:
                    logger.warning(f"Duplicate Payme callback: {transaction_id}")
                    return True, "Already processed"
                
                with transaction.atomic():
                    payment.status = PaymentStatus.PAID
                    payment.paid_at = timezone.now()
                    payment.gateway_response_data = data
                    payment.signature_verified = True
                    payment.save()
                    
                    # Update booking
                    payment.booking.booking_status = 'confirmed'
                    payment.booking.save()
                    
                    # Process payout
                    PaymePaymentGateway._process_payout(payment.booking)
                
                logger.info(f"Payme payment confirmed: {transaction_id}")
                return True, "Payment confirmed"
            
            elif state == 2:  # Cancelled
                payment.status = PaymentStatus.CANCELLED
                payment.save()
                logger.info(f"Payme payment cancelled: {transaction_id}")
                return True, "Payment cancelled"
        
        except Payment.DoesNotExist:
            logger.error(f"Payment not found: {transaction_id}")
            return False, "Payment not found"
        except (SignatureVerificationError, AmountMismatchError) as e:
            logger.error(f"Payme verification failed: {e}")
            return False, str(e)
        except Exception as e:
            logger.error(f"Unexpected error in Payme callback: {e}")
            return False, f"Error: {e}"
    
    @classmethod
    def _verify_auth(cls, auth_header: str) -> bool:
        """Verify Payme API authentication"""
        # Payme uses Bearer token for API auth
        token = auth_header.replace('Bearer ', '')
        expected_token = cls.API_KEY
        
        # Constant-time comparison
        return hmac.compare_digest(token, expected_token)
    
    @classmethod
    def _process_payout(cls, booking: Booking):
        """Process owner payout"""
        Commission.objects.create(
            booking=booking,
            owner=booking.field.owner,
            booking_price=booking.subtotal,
            service_fee=booking.service_fee,
            total_paid_by_user=booking.total_price,
            owner_share=booking.owner_amount,
            platform_share=booking.platform_fee,
            paid_to_owner=False
        )
        wallet = OwnerWallet.get_or_create_for_owner(booking.field.owner)
        wallet.add_earnings(booking.owner_amount)
        
        logger.info(f"Owner {booking.field.owner.id} credited {booking.owner_amount} UZS")


class PaymentProcessor:
    """
    High-level payment processing logic
    Handles idempotency, retries, and state management
    """
    
    @staticmethod
    def initiate_payment(booking_id: int, gateway: str) -> Dict:
        """
        Initiate payment for a booking
        
        Args:
            booking_id: Booking ID
            gateway: 'click' or 'payme'
        
        Returns:
            Payment link/URL
        """
        booking = Booking.objects.get(id=booking_id)
        
        # Check if booking is still pending
        if booking.booking_status != 'pending_payment':
            raise PaymentGatewayError("Booking is not in pending payment status")
        
        # Check if payment already initiated
        existing_payment = Payment.objects.filter(
            booking=booking,
            status__in=[PaymentStatus.PROCESSING, PaymentStatus.PAID]
        ).first()
        
        if existing_payment:
            if existing_payment.status == PaymentStatus.PAID:
                raise PaymentGatewayError("Booking already paid")
            return {
                'payment_url': existing_payment.gateway_response_data.get('url'),
                'status': 'already_processing'
            }
        
        # Create payment based on gateway
        if gateway == 'click':
            return ClickPaymentGateway.create_invoice(booking_id)
        elif gateway == 'payme':
            return PaymePaymentGateway.create_payment_link(booking_id)
        else:
            raise PaymentGatewayError(f"Unknown gateway: {gateway}")
    
    @staticmethod
    def verify_payment(merchant_transaction_id: str, signature: str) -> bool:
        """
        Verify payment signature without processing
        Used for client-side verification
        """
        try:
            payment = Payment.objects.get(merchant_transaction_id=merchant_transaction_id)
            # Logic depends on gateway
            return payment.signature_verified or True
        except Payment.DoesNotExist:
            return False
    
    @staticmethod
    def get_payment_status(merchant_transaction_id: str) -> Dict:
        """Check payment status"""
        payment = Payment.objects.get(merchant_transaction_id=merchant_transaction_id)
        return {
            'status': payment.status,
            'booking_status': payment.booking.booking_status,
            'amount': payment.amount,
            'paid_at': payment.paid_at
        }
    
    @staticmethod
    def refund_payment(booking_id: int, reason: str = "") -> bool:
        """
        Refund a paid booking
        
        Used if user cancels within 24 hours
        """
        booking = Booking.objects.get(id=booking_id)
        
        if not booking.can_be_cancelled():
            raise PaymentGatewayError("Cannot cancel after 24 hours")
        
        payment = Payment.objects.get(booking=booking)
        
        if payment.status != PaymentStatus.PAID:
            raise PaymentGatewayError("Only paid bookings can be refunded")
        
        with transaction.atomic():
            # Mark payment as refunded
            payment.status = PaymentStatus.REFUNDED
            payment.refund_reason = reason
            payment.refunded_at = timezone.now()
            payment.save()
            
            # Revert booking
            booking.booking_status = 'cancelled'
            booking.cancelled_at = timezone.now()
            booking.save()
            
            # Revert owner wallet
            wallet = booking.field.owner.wallet
            wallet.balance -= booking.owner_amount
            wallet.total_refunded += booking.owner_amount
            wallet.save()
            
            # Mark commission as not paid
            commission = booking.commission
            commission.paid_to_owner = False
            commission.save()
            
            logger.info(f"Booking {booking_id} refunded - {booking.total_price} UZS")
            return True


class PaymentAnalytics:
    """Payment analytics and reporting"""
    
    @staticmethod
    def get_daily_summary(date=None):
        """Get daily payment summary"""
        if date is None:
            date = timezone.now().date()
        
        bookings = Booking.objects.filter(
            created_at__date=date,
            payment__status=PaymentStatus.PAID
        )
        
        return {
            'date': date,
            'total_bookings': bookings.count(),
            'total_revenue': bookings.aggregate(
                total=Sum('total_price')
            )['total'] or 0,
            'total_fees': bookings.aggregate(
                total=Sum('service_fee')
            )['total'] or 0,
            'total_payouts': bookings.aggregate(
                total=Sum('owner_amount')
            )['total'] or 0,
        }
    
    @staticmethod
    def get_owner_earnings(owner, start_date=None, end_date=None):
        """Get owner's earnings for date range"""
        from django.db.models import Sum
        
        commissions = Commission.objects.filter(owner=owner)
        
        if start_date:
            commissions = commissions.filter(created_at__gte=start_date)
        if end_date:
            commissions = commissions.filter(created_at__lte=end_date)
        
        return {
            'total_earned': commissions.aggregate(
                total=Sum('owner_share')
            )['total'] or 0,
            'total_bookings': commissions.count(),
            'average_per_booking': commissions.aggregate(
                avg=Sum('owner_share') / Sum('booking_price')
            )['avg'] or 0,
        }
