from datetime import timedelta

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
import random

from django.utils import timezone


# Create your models here.

class Amenity(models.Model):
    name = models.CharField(max_length=500)

    def __str__(self):
        return self.name


class FieldStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"

class FieldCard(models.Model):
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="fields")

    name = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    description = models.TextField()
    price_per_hour = models.PositiveIntegerField()

    length_m = models.PositiveSmallIntegerField(null=True, blank=True)
    width_m = models.PositiveSmallIntegerField(null=True, blank=True)

    image = models.ImageField(upload_to='fields/')
    created_at = models.DateTimeField(auto_now_add=True)

    amenities = models.ManyToManyField(Amenity, blank=True)

    status = models.CharField(max_length=20, choices=FieldStatus.choices, default=FieldStatus.PENDING)
    admin_note = models.TextField(blank=True)  # rad qilsa sabab

    def __str__(self):
        return self.name



class FieldImage(models.Model):
    field = models.ForeignKey(FieldCard, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='field_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.field.name} image {self.id}"


class Review(models.Model):
    field = models.ForeignKey(FieldCard, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.field.name} - {self.rating}"


class BookingStatus(models.TextChoices):
    WAITING_PAYMENT = "waiting_payment", "Waiting payment"
    VERIFIED = "verified", "Verified"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"

class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class Booking(models.Model):
    field = models.ForeignKey(FieldCard, on_delete=models.CASCADE, related_name="bookings")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")

    date = models.DateField()
    start_time = models.TimeField()
    duration_hours = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])

    service_fee = models.PositiveIntegerField(default=5000)
    subtotal = models.PositiveIntegerField(default=0)
    total_price = models.PositiveIntegerField(default=0)

    platform_fee = models.PositiveIntegerField(default=5000)
    owner_amount = models.PositiveIntegerField(default=0)
    
    # Ticket used for discount (ten=10%, twenty=20%, fifty=50%, free=100%)
    ticket_used = models.CharField(
        max_length=20,
        choices=[('ten', '10%'), ('twenty', '20%'), ('fifty', '50%'), ('free', '100%')],
        null=True,
        blank=True
    )

    # 6-digit verification code (1 million possibilities, brute-force resistant)
    verification_code = models.CharField(max_length=6, db_index=True, blank=True)
    verification_code_hash = models.CharField(max_length=255, blank=True)
    verification_attempts = models.PositiveSmallIntegerField(default=0)
    verification_locked_until = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.WAITING_PAYMENT
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING
    )

    created_at = models.DateTimeField(auto_now_add=True)
    payment_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["field", "date", "start_time"], name="uniq_field_slot")
        ]

    def save(self, *args, **kwargs):
        if not self.verification_code:
            import secrets
            from django.contrib.auth.hashers import make_password
            # Generate 6-digit secure code (1 million possibilities)
            code = f"{secrets.randbelow(1000000):06d}"
            self.verification_code = code
            # Store hash for safe comparison
            self.verification_code_hash = make_password(code)

        self.subtotal = self.field.price_per_hour * self.duration_hours
        self.service_fee = 5000
        # Platform fee is the extra charged to the user; owner still gets the full booking subtotal.
        # Keeping platform_fee separate allows us to show owner earnings without revealing the fee.
        self.platform_fee = 5000
        self.total_price = self.subtotal + self.service_fee
        # Owner gets full subtotal (UI must not show commission breakdown)
        self.owner_amount = self.subtotal

        if self.status == BookingStatus.WAITING_PAYMENT and not self.payment_expires_at:
            self.payment_expires_at = timezone.now() + timedelta(minutes=5)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.field.name} | {self.date} {self.start_time} | {self.user.username}"


class IdempotencyKey(models.Model):
    """Track idempotency keys for booking creation to ensure clients can safely retry."""
    key = models.CharField(max_length=255, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='idempotency_keys')
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Idempotency {self.key} user={self.user_id} booking={self.booking_id}"


class BookingLog(models.Model):
    """Audit log for booking attempts and state changes."""
    ACTION_CHOICES = [
        ("attempt", "Attempt"),
        ("success", "Success"),
        ("failure", "Failure"),
        ("cancel", "Cancel"),
    ]
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, null=True, blank=True, related_name='logs')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    detail = models.TextField(blank=True)
    ip = models.CharField(max_length=45, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"BookingLog {self.action} by {self.user_id} at {self.created_at}"


class TicketType(models.TextChoices):
    DISCOUNT_10 = "discount_10", "10% Discount"
    DISCOUNT_20 = "discount_20", "20% Discount"
    DISCOUNT_50 = "discount_50", "50% Discount"
    FREE_FIELD = "free_field", "Free Field"


class TicketConfig(models.Model):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True)

    def __str__(self):
        return "Ticket Shop Config"


class TicketItem(models.Model):
    config = models.ForeignKey(TicketConfig, on_delete=models.CASCADE, related_name="items")
    type = models.CharField(max_length=30, choices=TicketType.choices)
    price_coins = models.PositiveIntegerField()

    class Meta:
        unique_together = ("config", "type")

    def __str__(self):
        return f"{self.get_type_display()} ({self.price_coins} coins)"


class UserTicket(models.Model):
    """Track user's purchased discount tickets (10%, 20%, 50%, free field)"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="tickets")
    
    # Ticket counts for each type
    tickets_ten = models.PositiveIntegerField(default=0)      # 10% discount
    tickets_twenty = models.PositiveIntegerField(default=0)   # 20% discount
    tickets_fifty = models.PositiveIntegerField(default=0)    # 50% discount
    tickets_free = models.PositiveIntegerField(default=0)     # Free field (100% discount)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "User Tickets"
    
    def __str__(self):
        return f"{self.user.username} - 10%:{self.tickets_ten} 20%:{self.tickets_twenty} 50%:{self.tickets_fifty} Free:{self.tickets_free}"
    
    def get_total_tickets(self):
        """Return total count of all tickets"""
        return self.tickets_ten + self.tickets_twenty + self.tickets_fifty + self.tickets_free
    
    def decrement_ticket(self, ticket_type):
        """Decrement ticket count for given type. Returns True if successful."""
        if ticket_type == 'ten' and self.tickets_ten > 0:
            self.tickets_ten -= 1
            self.save()
            return True
        elif ticket_type == 'twenty' and self.tickets_twenty > 0:
            self.tickets_twenty -= 1
            self.save()
            return True
        elif ticket_type == 'fifty' and self.tickets_fifty > 0:
            self.tickets_fifty -= 1
            self.save()
            return True
        elif ticket_type == 'free' and self.tickets_free > 0:
            self.tickets_free -= 1
            self.save()
            return True
        return False


class PaymentMethod(models.TextChoices):
    CLICK = "click", "Click"
    PAYME = "payme", "Payme"
    OTHER = "other", "Other"


class Payment(models.Model):
    booking = models.OneToOneField("Booking", on_delete=models.CASCADE, related_name="payment")

    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    amount = models.PositiveIntegerField()

    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)

    # Click/Payme dan keladigan transaction id/order id (keyin integratsiya qilganda kerak bo‘ladi)
    provider_transaction_id = models.CharField(max_length=128, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.booking.id} - {self.method} - {self.status}"


class UserType(models.TextChoices):
    REGULAR = "regular", "Regular User"
    OWNER = "owner", "Field Owner"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    # Phone must be unique and required for account reuse rules
    phone = models.CharField(max_length=20, unique=True)   # +998...
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    user_type = models.CharField(max_length=20, choices=UserType.choices, default=UserType.REGULAR)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.phone} ({self.user_type})"

class OTPCode(models.Model):
    phone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=255, blank=True, default='')
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["phone", "created_at"]),
        ]
    
    def verify_code(self, code_attempt):
        """Timing-safe code verification with attempt limiting"""
        from django.contrib.auth.hashers import check_password
        
        # Normalize input
        code_str = str(code_attempt).strip() if code_attempt else ""
        
        print(f"[DEBUG] verify_code called:")
        print(f"        - code_hash exists: {bool(self.code_hash)}, length: {len(self.code_hash) if self.code_hash else 0}")
        print(f"        - code_attempt: '{code_str}', length: {len(code_str)}")
        print(f"        - is_used: {self.is_used}, now: {timezone.now()}, expires: {self.expires_at}")
        
        if self.is_used:
            print(f"[DEBUG] Code already used")
            return False
            
        if timezone.now() > self.expires_at:
            print(f"[DEBUG] Code expired - now: {timezone.now()}, expires: {self.expires_at}")
            return False
        
        if self.attempts >= self.max_attempts:
            print(f"[DEBUG] Max attempts reached: {self.attempts}/{self.max_attempts}")
            return False
        
        # Verify hash exists and is valid
        if not self.code_hash or not self.code_hash.strip():
            print(f"[DEBUG] ERROR: code_hash is empty or invalid")
            self.attempts += 1
            self.save(update_fields=['attempts'])
            return False
        
        # Validate code format (should be 6 digits)
        if not code_str or len(code_str) != 6 or not code_str.isdigit():
            print(f"[DEBUG] Code format invalid - expected 6 digits, got: '{code_str}'")
            self.attempts += 1
            self.save(update_fields=['attempts'])
            return False
        
        # Increment attempts first
        self.attempts += 1
        self.save(update_fields=['attempts'])
        
        # Timing-safe comparison
        try:
            result = check_password(code_str, self.code_hash)
            print(f"[DEBUG] check_password result: {result}, attempts now: {self.attempts}/{self.max_attempts}")
            return result
        except Exception as e:
            print(f"[DEBUG] Exception during check_password: {type(e).__name__}: {e}")
            return False


class OTPRateLimit(models.Model):
    """Track OTP requests per phone and IP to prevent brute force and spam"""
    phone = models.CharField(max_length=20, db_index=True)
    ip_address = models.CharField(max_length=45, db_index=True)
    request_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    window_start = models.DateTimeField(db_index=True)  # 1-hour sliding window
    
    class Meta:
        unique_together = (('phone', 'ip_address', 'window_start'),)
        indexes = [
            models.Index(fields=['phone', '-window_start']),
            models.Index(fields=['ip_address', '-window_start']),
        ]
    
    def __str__(self):
        return f"OTPRateLimit {self.phone} from {self.ip_address}"


class WebhookLog(models.Model):
    """Log all webhooks to ensure idempotency (prevent duplicate payment processing)"""
    WEBHOOK_STATUS = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    provider = models.CharField(max_length=20)  # 'click', 'payme', etc
    transaction_id = models.CharField(max_length=255, unique=True, db_index=True)
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=WEBHOOK_STATUS, default='pending')
    payload = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['provider', 'status']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.provider} {self.transaction_id} - {self.status}"

    def __str__(self):
        return f"{self.phone} - {self.code} - used={self.is_used}"


# ------------------------------------------------------------
# Security monitoring/logging model used by middleware
# ------------------------------------------------------------
class SecurityIncident(models.Model):
    """Tracks abusive behaviour per IP for dashboard/auto‑ban purposes."""

    ip = models.CharField(max_length=45, db_index=True)
    last_path = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    banned_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Security incident"
        verbose_name_plural = "Security incidents"

    def __str__(self):
        return f"{self.ip} ({self.attempts} attempts)"


class FieldSlot(models.Model):
    field = models.ForeignKey(FieldCard, on_delete=models.CASCADE, related_name="slots")

    date = models.DateField()
    start_time = models.TimeField()

    is_booked = models.BooleanField(default=False)

    booking = models.ForeignKey(
        "Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reserved_slots"
    )

    class Meta:
        unique_together = ("field", "date", "start_time")

    def __str__(self):
        return f"{self.field.name} {self.date} {self.start_time}"


class OwnerCard(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name="card")
    card_number = models.CharField(max_length=19)  # Store masked card number only: **** **** **** 1234
    expiry_date = models.CharField(max_length=5)  # MM/YY
    cvv = models.CharField(max_length=4, blank=True)  # Do not persist real CVV
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.owner.username}'s card {self.card_number}"

    def set_masked_card(self, card_number, expiry_date):
        last4 = card_number[-4:]
        self.card_number = f"**** **** **** {last4}"
        self.expiry_date = expiry_date
        self.cvv = ''



class PaymentGateway(models.TextChoices):
    CLICK = "click", "Click"
    PAYME = "payme", "Payme"
    UZCARD = "uzcard", "Uzcard"


class PlatformBalance(models.Model):
    date = models.DateField(unique=True, db_index=True, default=None, null=True)
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
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        verbose_name_plural = "Platform Balances"

    def __str__(self):
        return f"Platform Balance - {self.date} - {self.total_revenue:,} UZS"

    @classmethod
    def get_or_create_today(cls):
        from django.utils import timezone
        today = timezone.now().date()
        return cls.objects.get_or_create(date=today)[0]

    @classmethod
    def update_daily_summary(cls):
        from django.utils import timezone
        today = timezone.now().date()
        balance = cls.get_or_create_today()
        bookings = Booking.objects.filter(
            created_at__date=today,
            booking_status__in=[BookingStatus.CONFIRMED, BookingStatus.COMPLETED],
            payment__status=PaymentStatus.PAID
        )
        balance.total_bookings = bookings.count()
        balance.total_revenue = bookings.aggregate(total=Sum('total_price'))['total'] or 0
        balance.total_fees = bookings.aggregate(total=Sum('platform_amount'))['total'] or 0
        balance.total_payouts = bookings.aggregate(total=Sum('owner_amount'))['total'] or 0
        if bookings.exists():
            total_price = sum(b.total_price for b in bookings)
            balance.average_booking_price = total_price // len(bookings)
        balance.save()


class OwnerBalance(models.Model):
    owner = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="balance"
    )

    total_earned = models.PositiveBigIntegerField(default=0)
    available_balance = models.PositiveBigIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        owner_name = self.owner.username if self.owner else "[None]"
        return f"{owner_name} - {self.available_balance} so'm"


class OwnerWallet(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name="wallet")
    balance = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    total_earned = models.BigIntegerField(default=0)
    total_withdrawn = models.BigIntegerField(default=0)
    total_refunded = models.BigIntegerField(default=0)
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
        return cls.objects.get_or_create(owner=owner)[0]

    def add_earnings(self, amount, commission_id=None):
        self.balance += amount
        self.total_earned += amount
        self.save()

    def withdraw(self, amount, bank_account):
        with transaction.atomic():
            self.refresh_from_db(select_for_update=True)
            if self.balance < amount:
                raise ValueError("Insufficient balance")
            self.balance -= amount
            self.total_withdrawn += amount
            self.last_payout_at = timezone.now()
            self.save()
            Withdrawal.objects.create(
                wallet=self,
                amount=amount,
                bank_account=bank_account,
                status=WithdrawalStatus.PENDING
            )

    def get_daily_earnings(self, date):
        return self.owner.commissions.filter(
            created_at__date=date,
            paid_to_owner=True
        ).aggregate(total=Sum('owner_share'))['total'] or 0

    def get_monthly_earnings(self, year, month):
        return self.owner.commissions.filter(
            created_at__year=year,
            created_at__month=month,
            paid_to_owner=True
        ).aggregate(total=Sum('owner_share'))['total'] or 0


class Commission(models.Model):
    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name="commission"
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="commissions")
    booking_price = models.PositiveIntegerField()
    service_fee = models.PositiveIntegerField()
    total_paid_by_user = models.PositiveIntegerField()
    owner_share = models.PositiveIntegerField()
    platform_share = models.PositiveIntegerField()
    paid_to_owner = models.BooleanField(default=False)
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


class WithdrawStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class WithdrawRequest(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)

    amount = models.PositiveIntegerField()

    card_number = models.CharField(max_length=32)
    card_holder = models.CharField(max_length=120)

    status = models.CharField(
        max_length=20,
        choices=WithdrawStatus.choices,
        default=WithdrawStatus.PENDING
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.owner.username} - {self.amount}"


# ---------- Support / Helpdesk ----------

class SupportTicketStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


class SupportTicket(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(
        max_length=20,
        choices=SupportTicketStatus.choices,
        default=SupportTicketStatus.OPEN,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        owner = self.user.username if self.user else self.phone or "anonymous"
        return f"Support ticket ({owner})"


class SupportMessage(models.Model):
    SENDER_USER = "user"
    SENDER_SUPPORT = "support"

    SENDER_CHOICES = [
        (SENDER_USER, "User"),
        (SENDER_SUPPORT, "Support"),
    ]

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=20, choices=SENDER_CHOICES, default=SENDER_USER)
    content = models.TextField()
    agent = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    def __str__(self):
        agent_part = f" by {self.agent.username}" if self.agent else ""
        return f"[{self.get_sender_display()}]{agent_part} {self.content[:20]}"


