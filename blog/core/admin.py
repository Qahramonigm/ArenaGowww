from django import forms
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm

from .models import (
    Amenity, FieldCard, Review,
    Booking, Payment,
    TicketConfig, TicketItem, FieldStatus,
    UserProfile, OTPCode, UserType, PlatformBalance, OwnerBalance, WithdrawRequest, OwnerWallet,
    SupportTicket, SupportMessage,
    SecurityIncident,
)


# --------- Custom forms (User + Profile birga) ----------
class CustomUserCreationForm(UserCreationForm):
    phone = forms.CharField(required=True)
    age = forms.IntegerField(required=False)
    user_type = forms.ChoiceField(choices=UserType.choices, required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "first_name", "last_name", "phone", "age", "user_type")

    def save(self, commit=True):
        user = super().save(commit=commit)
        # profile yaratamiz
        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "phone": self.cleaned_data["phone"],
                "age": self.cleaned_data.get("age"),
                "user_type": self.cleaned_data["user_type"],
            }
        )
        return user


class CustomUserChangeForm(UserChangeForm):
    phone = forms.CharField(required=False)
    age = forms.IntegerField(required=False)
    user_type = forms.ChoiceField(choices=UserType.choices, required=False)

    class Meta(UserChangeForm.Meta):
        model = User
        fields = ("username", "email", "first_name", "last_name", "phone", "age", "user_type")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, "profile"):
            self.fields["phone"].initial = self.instance.profile.phone
            self.fields["age"].initial = self.instance.profile.age
            self.fields["user_type"].initial = self.instance.profile.user_type
        if self.instance and self.instance.email and self.instance.email.endswith("@temp.com"):
            self.fields["email"].initial = ""

    def save(self, commit=True):
        user = super().save(commit=commit)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        phone = self.cleaned_data.get("phone")
        if phone:
            profile.phone = phone
        profile.age = self.cleaned_data.get("age")
        ut = self.cleaned_data.get("user_type")
        if ut:
            profile.user_type = ut
        profile.save()
        return user


# --------- Filter: Owner/Regular ----------
class UserTypeFilter(admin.SimpleListFilter):
    title = "User type"
    parameter_name = "user_type"

    def lookups(self, request, model_admin):
        return [
            (UserType.REGULAR, "Regular"),
            (UserType.OWNER, "Owner"),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(profile__user_type=self.value())
        return queryset


# --------- Profile inline (edit sahifada ko‘rinadi) ----------
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0


# oldingi User adminni xavfsiz unregister
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm

    inlines = [UserProfileInline]

    # Display: ID, full name, phone, email, type, staff status (hide username if auto-generated)
    list_display = ("get_user_id", "get_full_name", "get_phone", "get_email", "get_user_type", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name", "profile__phone", "id")
    list_select_related = ("profile",)
    # Filter by user_type (direction), staff, superuser, active status
    list_filter = (UserTypeFilter, "is_staff", "is_superuser", "is_active")

    def get_full_name(self, obj):
        full_name = obj.get_full_name().strip()
        if full_name:
            return full_name

        # If no first/last name provided, avoid showing auto-generated username.
        # Show placeholder until the user sets name fields.
        return "—"
    get_full_name.short_description = "To'liq ism/familya"
    
    # Organize columns by type
    fieldsets = (
        ("Identifikatsiya", {
            "fields": ("id", "username", "email")
        }),
        ("Foydalanuvchi ma'lumotlari", {
            "fields": ("first_name", "last_name"),
            "classes": ("collapse",)
        }),
        ("Ruxsatlar", {
            "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
            "classes": ("collapse",)
        }),
    )
    
    readonly_fields = ("id",)

    def get_user_id(self, obj):
        return obj.id
    get_user_id.short_description = "ID"
    
    def get_phone(self, obj):
        return getattr(getattr(obj, "profile", None), "phone", "")
    get_phone.short_description = "Telefon"

    def get_email(self, obj):
        email = obj.email or ""
        if email.endswith("@temp.com"):
            return ""
        return email
    get_email.short_description = "Email"

    def get_age(self, obj):
        return getattr(getattr(obj, "profile", None), "age", None)
    get_age.short_description = "Yosh"

    def get_user_type(self, obj):
        prof = getattr(obj, "profile", None)
        return getattr(prof, "get_user_type_display", lambda: "")()
    get_user_type.short_description = "Turi (Direction)"


# ---------- OTP Codes ----------
@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ("id", "phone", "get_code_display", "is_used", "expires_at", "created_at")
    list_filter = ("is_used",)
    search_fields = ("phone",)
    readonly_fields = ("phone", "is_used", "attempts", "created_at", "expires_at")
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def get_code_display(self, obj):
        from django.utils import timezone
        time_diff = timezone.now() - obj.created_at
        if time_diff.total_seconds() <= 180:
            # Code is stored hashed for security. Do not expose raw OTP.
            return "(hidden)"
        return "Expired"

    get_code_display.short_description = "Code"


# ---------- Amenities ----------
@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


# ---------- Fields ----------
@admin.register(FieldCard)
class FieldCardAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "owner_info", "city", "district", "price_per_hour", "status", "created_at")
    list_filter = ("status", "city", "district", "owner__profile__user_type")
    search_fields = ("name", "address", "owner__id", "owner__username", "owner__profile__phone")
    list_select_related = ("owner", "owner__profile")
    readonly_fields = ("created_at", "id")
    
    actions = ["approve_fields", "reject_fields"]

    def owner_info(self, obj):
        if not obj.owner:
            return "—"
        prof = getattr(obj.owner, "profile", None)
        phone = getattr(prof, "phone", "")
        user_type = getattr(prof, "get_user_type_display", lambda: "")()
        return f"{obj.owner.id} - {obj.owner.username} ({phone}) [{user_type}]"
    owner_info.short_description = "Owner (ID - Name - Phone - Type)"

    @admin.action(description="Approve selected fields")
    def approve_fields(self, request, queryset):
        queryset.update(status=FieldStatus.APPROVED, admin_note="")

    @admin.action(description="Reject selected fields")
    def reject_fields(self, request, queryset):
        queryset.update(status=FieldStatus.REJECTED)


# ---------- Reviews ----------
@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "field", "user", "rating", "created_at")
    list_filter = ("rating", "created_at")
    search_fields = ("field__name", "user__username", "comment")
    readonly_fields = ("created_at",)


# ---------- Bookings ----------
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "id", "field_owner", "user_info",
        "date", "start_time", "duration_hours",
        "total_price", "status", "payment_status", "created_at"
    )
    readonly_fields = ("subtotal", "service_fee", "total_price", "created_at", "verification_code")
    list_filter = ("status", "payment_status", "date", "user__profile__user_type", "field__owner__profile__user_type")
    search_fields = ("id", "field__name", "field__owner__id", "user__id", "user__username", "user__profile__phone", "verification_code")
    list_select_related = ("field", "field__owner", "field__owner__profile", "user", "user__profile")
    list_editable = ("status", "payment_status")

    def field_owner(self, obj):
        if not obj.field.owner:
            return f"Field: {obj.field.name} | Owner: [None]"
        prof = getattr(obj.field.owner, "profile", None)
        phone = getattr(prof, "phone", "")
        user_type = getattr(prof, "get_user_type_display", lambda: "")()
        return f"Field: {obj.field.name} | Owner: {obj.field.owner.id} ({user_type})"
    field_owner.short_description = "Field - Owner"

    def user_info(self, obj):
        if not obj.user:
            return "(deleted user)"
        prof = getattr(obj.user, "profile", None)
        phone = getattr(prof, "phone", "")
        user_type = getattr(prof, "get_user_type_display", lambda: "")()
        return f"{obj.user.id} - {obj.user.username} ({phone}) [{user_type}]"
    user_info.short_description = "User (ID - Name - Phone - Type)"


# ---------- Payments ----------
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "method", "amount", "status", "paid_at", "created_at")
    list_filter = ("method", "status", "created_at", "paid_at")
    search_fields = ("booking__id", "provider_transaction_id")
    readonly_fields = ("created_at", "paid_at")


# ---------- Security incidents ----------

@admin.register(SecurityIncident)
class SecurityIncidentAdmin(admin.ModelAdmin):
    list_display = ("ip", "last_path", "attempts", "banned_until", "created_at")
    readonly_fields = ("ip", "last_path", "attempts", "banned_until", "created_at", "updated_at")
    search_fields = ("ip",)
    list_filter = ("banned_until",)
    ordering = ("-created_at",)


# ---------- Ticket Shop (Config + Items) ----------
class TicketItemInline(admin.TabularInline):
    model = TicketItem
    extra = 0
    can_delete = False
    max_num = 4

    def has_add_permission(self, request, obj=None):
        if obj is None:
            return False
        return obj.items.count() < 4


@admin.register(TicketConfig)
class TicketConfigAdmin(admin.ModelAdmin):
    inlines = [TicketItemInline]

    def has_add_permission(self, request):
        return not TicketConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TicketItem)
class TicketItemAdmin(admin.ModelAdmin):
    list_display = ("type", "price_coins", "config")
    list_editable = ("price_coins",)

    def has_add_permission(self, request):
        return False



@admin.register(PlatformBalance)
class PlatformBalanceAdmin(admin.ModelAdmin):
    list_display = ("date", "total_revenue", "total_bookings", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(OwnerBalance)
class OwnerBalanceAdmin(admin.ModelAdmin):
    list_display = (
        "owner",
        "total_earned",
        "available_balance",
        "updated_at"
    )


@admin.register(OwnerWallet)
class OwnerWalletAdmin(admin.ModelAdmin):
    list_display = (
        "owner",
        "balance",
        "total_earned",
        "total_withdrawn",
        "last_payout_at",
        "next_payout_date",
    )
    list_select_related = ("owner",)
    readonly_fields = ("last_payout_at", "total_earned", "total_withdrawn")


@admin.register(WithdrawRequest)
class WithdrawRequestAdmin(admin.ModelAdmin):
    list_display = (
        "owner",
        "amount",
        "card_number",
        "status",
        "created_at"
    )

    list_editable = ("status",)


# ---------- Support ----------

class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 1
    # allow admin to type reply text; created messages will be marked as Support sender
    fields = ("content",)
    readonly_fields = ("created_at",)


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "user_info", "phone", "status", "agent_info", "created_at")
    list_filter = ("status", "created_at", "user__profile__user_type")
    search_fields = ("id", "user__id", "user__username", "phone", "agent__username")
    list_select_related = ("user", "user__profile", "agent")
    inlines = [SupportMessageInline]

    def user_info(self, obj):
        if not obj.user:
            return "(deleted user)"
        prof = getattr(obj.user, "profile", None)
        user_type = getattr(prof, "get_user_type_display", lambda: "")()
        return f"{obj.user.id} - {obj.user.username} [{user_type}]"
    user_info.short_description = "User (ID - Name - Type)"

    def agent_info(self, obj):
        if obj.agent:
            return f"{obj.agent.id} - {obj.agent.username}"
        return "Unassigned"
    agent_info.short_description = "Agent (ID - Name)"

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, SupportMessage):
                if not obj.pk:
                    obj.sender = SupportMessage.SENDER_SUPPORT
                    if request and hasattr(request, "user"):
                        obj.agent = request.user
                obj.save()
        formset.save_m2m()


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket_info", "user_agent_info", "created_at")
    list_filter = ("sender", "created_at")
    search_fields = ("id", "ticket__id", "ticket__user__id", "agent__id", "content")
    readonly_fields = ("ticket", "sender", "content", "created_at")
    list_select_related = ("ticket", "ticket__user", "ticket__user__profile", "agent")

    def ticket_info(self, obj):
        """Display ticket ID and user"""
        if not obj.ticket.user:
            return f"Ticket #{obj.ticket.id} | User: (deleted)"
        prof = getattr(obj.ticket.user, "profile", None)
        phone = getattr(prof, "phone", "")
        return f"Ticket #{obj.ticket.id} | User: {obj.ticket.user.id} ({obj.ticket.user.username}) {phone}"
    ticket_info.short_description = "Ticket Info"

    def user_agent_info(self, obj):
        """Display sender and who responded"""
        sender_name = "User" if obj.sender == SupportMessage.SENDER_USER else "Support"
        if obj.agent and obj.sender == SupportMessage.SENDER_SUPPORT:
            return f"{sender_name} - Agent: {obj.agent.id} ({obj.agent.username})"
        return sender_name
    user_agent_info.short_description = "Sender - Agent"













