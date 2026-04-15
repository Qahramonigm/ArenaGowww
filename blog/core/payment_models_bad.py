from .models import (
    FieldCard, Booking, User, BookingStatus, PaymentStatus,
    Payment, PlatformBalance, OwnerBalance, Commission,
    OwnerWallet, Withdrawal, PaymentMethod, PaymentGateway
)
    date = models.DateField(auto_now_add=True, unique=True, db_index=True)
    total_bookings = models.PositiveIntegerField(default=0)
    total_revenue = models.BigIntegerField(default=0)
    total_fees = models.BigIntegerField(default=0)
    total_payouts = models.BigIntegerField(default=0)
    revenue_by_click = models.BigIntegerField(default=0)
    revenue_by_payme = models.BigIntegerField(default=0)
    successful_payments = models.PositiveIntegerField(default=0)
    failed_payments = models.PositiveIntegerField(default=0)
    refunded_payments = models.PositiveIntegerField(default=0)
    average_booking_price = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        verbose_name_plural = "Platform Balances"

    def __str__(self):
        return f"Platform Balance - {self.date} - {self.total_revenue:,} UZS"

    @classmethod
    def get_or_create_today(cls):
        today = timezone.now().date()
        return cls.objects.get_or_create(date=today)[0]

    @classmethod
    def update_daily_summary(cls):
        today = timezone.now().date()
        balance = cls.get_or_create_today()
        bookings = Booking.objects.filter(created_at__date=today, booking_status__in=[BookingStatus.CONFIRMED, BookingStatus.COMPLETED], payment__status=PaymentStatus.PAID)
        balance.total_bookings = bookings.count()
        balance.total_revenue = bookings.aggregate(total=Sum('total_price'))['total'] or 0
        balance.total_fees = bookings.aggregate(total=Sum('platform_amount'))['total'] or 0
        balance.total_payouts = bookings.aggregate(total=Sum('owner_amount'))['total'] or 0
        if bookings.exists():
            total_price = sum(b.total_price for b in bookings)
            balance.average_booking_price = total_price // len(bookings)
        balance.save()


class WithdrawalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Withdrawal(models.Model):
    wallet = models.ForeignKey(OwnerWallet, on_delete=models.CASCADE, related_name="withdrawals")
    amount = models.PositiveIntegerField()
    bank_account = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=WithdrawalStatus.choices, default=WithdrawalStatus.PENDING)
    transaction_id = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Withdrawal - {self.wallet.owner.username} - {self.amount} UZS"

class Payment(models.Model):
    """
    Payment transaction record
    Tracks all payment attempts and status
    """
    
    # Reference to booking
    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name="payment",
        help_text="Associated booking"
    )
    
    # Payment gateway details
    gateway = models.CharField(
        max_length=20,
        choices=PaymentGateway.choices,
        help_text="Which payment gateway processed this"
    )
    
    # Gateway transaction IDs
    gateway_transaction_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Payment gateway's transaction ID"
    )
    merchant_transaction_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Our internal transaction ID"
    )
    
    # Amount verification
    amount = models.PositiveIntegerField(
        help_text="Amount user paid (in UZS)"
    )
    
    # Payment status
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True
    )
    
    # Payment method (optional - for tracking)
    payment_method = models.CharField(
        max_length=50,
        blank=True,
        help_text="Card type, mobile money, etc."
    )
    
    # User phone/account for payment gateway
    user_phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="User's phone number used for payment"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    gateway_response_at = models.DateTimeField(null=True, blank=True)
    
    # Signature verification
    gateway_signature = models.CharField(
        max_length=512,
        blank=True,
        help_text="Gateway's signature for verification"
    )
    signature_verified = models.BooleanField(
        default=False,
        help_text="Whether we verified the signature"
    )
    
    # Webhook data (for debugging)
    gateway_response_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full response from payment gateway"
    )
    
    # Refund tracking
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_reason = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['booking', 'status']),
            models.Index(fields=['gateway_transaction_id']),
            models.Index(fields=['merchant_transaction_id']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"Payment {self.merchant_transaction_id} - {self.status}"
    
    def verify_amount(self, expected_amount):
        """Verify amount matches booking"""
        if self.amount != expected_amount:
            raise ValueError(
                f"Amount mismatch: received {self.amount}, expected {expected_amount}"
            )
        return True
    
    def mark_as_paid(self):
        """Mark payment as successful and update booking"""
        self.status = PaymentStatus.PAID
        self.paid_at = timezone.now()
        self.save()
        
        # Update booking
        self.booking.booking_status = BookingStatus.CONFIRMED
        self.booking.save()


class Commission(models.Model):
    """
    Track earnings per transaction
    Helps with financial reporting and owner payouts
    """
    
    # Reference
    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name="commission"
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="commissions"
    )
    
    # Amount breakdown
    booking_price = models.PositiveIntegerField(
        help_text="Field price (what owner receives)"
    )
    service_fee = models.PositiveIntegerField(
        help_text="Platform service fee"
    )
    total_paid_by_user = models.PositiveIntegerField(
        help_text="Total amount user paid"
    )
    
    # Owner share (usually booking_price)
    owner_share = models.PositiveIntegerField(
        help_text="Amount owner receives"
    )
    platform_share = models.PositiveIntegerField(
        help_text="Amount platform keeps"
    )
    
    # Payout status
    paid_to_owner = models.BooleanField(
        default=False,
        help_text="Whether owner has been paid"
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', 'paid_to_owner']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Commission #{self.id} - {self.owner.username} - {self.owner_share} UZS"


class OwnerWallet(models.Model):
    """
    Owner's wallet - tracks balance and transaction history
    """
    
    owner = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="wallet"
    )
    
    # Current balance (in UZS)
    balance = models.BigIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Current balance in UZS"
    )
    
    # All-time totals
    total_earned = models.BigIntegerField(
        default=0,
        help_text="Total earnings from bookings"
    )
    total_withdrawn = models.BigIntegerField(
        default=0,
        help_text="Total withdrawn to bank account"
    )
    total_refunded = models.BigIntegerField(
        default=0,
        help_text="Total refunded to customers"
    )
    
    # Last payout
    last_payout_at = models.DateTimeField(null=True, blank=True)
    next_payout_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Owner Wallets"
    
    def __str__(self):
        return f"{self.owner.username} - {self.balance:,} UZS"
    
    @classmethod
    def get_or_create_for_owner(cls, owner):
        """Get or create wallet for owner"""
        wallet, created = cls.objects.get_or_create(owner=owner)
        return wallet
    
    def add_earnings(self, amount, commission_id):
        """Add booking earnings to wallet"""
        self.balance += amount
        self.total_earned += amount
        self.save()
    
    def withdraw(self, amount, bank_account):
        """Withdraw money to bank account"""
        if self.balance < amount:
            raise ValueError("Insufficient balance")
        
        self.balance -= amount
        self.total_withdrawn += amount
        self.last_payout_at = timezone.now()
        self.save()
        
        # Create withdrawal record
        Withdrawal.objects.create(
            wallet=self,
            amount=amount,
            bank_account=bank_account,
            status=WithdrawalStatus.PENDING
        )
    
    def get_daily_earnings(self, date):
        """Get earnings for a specific date"""
        return self.owner.commissions.filter(
            created_at__date=date,
            paid_to_owner=True
        ).aggregate(total=Sum('owner_share'))['total'] or 0
    
    def get_monthly_earnings(self, year, month):
        """Get earnings for a specific month"""
        return self.owner.commissions.filter(
            created_at__year=year,
            created_at__month=month,
            paid_to_owner=True
        ).aggregate(total=Sum('owner_share'))['total'] or 0


class PlatformBalance(models.Model):
    """
    Platform's financial tracking
    Daily summaries for business intelligence
    """
    
    date = models.DateField(
        auto_now_add=True,
        unique=True,
        db_index=True
    )
    
    # Daily totals
    total_bookings = models.PositiveIntegerField(default=0)
    total_revenue = models.BigIntegerField(default=0)  # All money in
    total_fees = models.BigIntegerField(default=0)     # Platform fees
    total_payouts = models.BigIntegerField(default=0)  # To owners
    
    # Payment method breakdown
    revenue_by_click = models.BigIntegerField(default=0)
    revenue_by_payme = models.BigIntegerField(default=0)
    
    # Payment status breakdown
    successful_payments = models.PositiveIntegerField(default=0)
    failed_payments = models.PositiveIntegerField(default=0)
    refunded_payments = models.PositiveIntegerField(default=0)
    
    # Metrics
    average_booking_price = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date']
        verbose_name_plural = "Platform Balances"
    
    def __str__(self):
        return f"Platform Balance - {self.date} - {self.total_revenue:,} UZS"
    
    @classmethod
    def get_or_create_today(cls):
        """Get today's platform balance"""
        today = timezone.now().date()
        balance, created = cls.objects.get_or_create(date=today)
        return balance
    
    @classmethod
    def update_daily_summary(cls):
        """Recalculate today's summary from bookings"""
        from django.db.models import Count, Sum
        
        today = timezone.now().date()
        balance = cls.get_or_create_today()
        
        # Get all paid bookings for today
        bookings = Booking.objects.filter(
            created_at__date=today,
            booking_status__in=[BookingStatus.CONFIRMED, BookingStatus.COMPLETED],
            payment__status=PaymentStatus.PAID
        )
        
        balance.total_bookings = bookings.count()
        balance.total_revenue = bookings.aggregate(
            total=Sum('total_price')
        )['total'] or 0
        balance.total_fees = bookings.aggregate(
            total=Sum('platform_amount')
        )['total'] or 0
        balance.total_payouts = bookings.aggregate(
            total=Sum('owner_amount')
        )['total'] or 0
        balance.total_bookings = bookings.count()
        
        if bookings.exists():
            total_price = sum(b.total_price for b in bookings)
            balance.average_booking_price = total_price // len(bookings)
        
        balance.save()


class WithdrawalStatus(models.TextChoices):
    """Owner withdrawal statuses"""
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Withdrawal(models.Model):
    """Owner wallet withdrawals"""
    
    wallet = models.ForeignKey(
        OwnerWallet,
        on_delete=models.CASCADE,
        related_name="withdrawals"
    )
    
    amount = models.PositiveIntegerField(help_text="Withdrawal amount in UZS")
    
    bank_account = models.CharField(
        max_length=255,
        help_text="Bank account or payment method"
    )
    
    status = models.CharField(
        max_length=20,
        choices=WithdrawalStatus.choices,
        default=WithdrawalStatus.PENDING
    )
    
    transaction_id = models.CharField(max_length=255, blank=True)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Withdrawal - {self.wallet.owner.username} - {self.amount} UZS"
