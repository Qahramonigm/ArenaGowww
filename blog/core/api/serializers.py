"""
API Serializers for support system data marshalling.
Converts model instances to/from JSON representations.
"""
from rest_framework import serializers
from django.contrib.auth.models import User
from django.db.models import Avg
from ..models import SupportTicket, SupportMessage, UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['phone', 'age', 'user_type']
        read_only_fields = ['user_type']


class UserMinimalSerializer(serializers.ModelSerializer):
    """Minimal user info - avoid exposing sensitive data."""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email']
        read_only_fields = fields


class UserWithProfileSerializer(serializers.ModelSerializer):
    """User with profile info for auth flows - used by /api/auth/me/ and OTP verify."""
    profile = UserProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'profile']
        read_only_fields = fields


class SupportMessageSerializer(serializers.ModelSerializer):
    """Represents a single message in a conversation."""
    
    agent_name = serializers.CharField(
        source='agent.username',
        read_only=True,
        allow_null=True,
        required=False
    )
    sender_display = serializers.CharField(
        source='get_sender_display',
        read_only=True
    )
    
    class Meta:
        model = SupportMessage
        fields = [
            'id',
            'sender',
            'sender_display',
            'content',
            'created_at',
            'read',
            'agent_name',
        ]
        read_only_fields = ['id', 'sender_display', 'created_at', 'read', 'agent_name']


class SupportTicketListSerializer(serializers.ModelSerializer):
    """
    Simplified ticket info for list views (agent dashboard).
    Includes unread count and latest message preview.
    """
    
    username = serializers.SerializerMethodField()
    user_email = serializers.CharField(
        source='user.email',
        read_only=True,
        allow_null=True
    )
    unread_count = serializers.SerializerMethodField()
    latest_message = serializers.SerializerMethodField()
    latest_time = serializers.SerializerMethodField()
    
    class Meta:
        model = SupportTicket
        fields = [
            'id',
            'username',
            'user_email',
            'phone',
            'status',
            'created_at',
            'unread_count',
            'latest_message',
            'latest_time',
        ]
        read_only_fields = fields
    
    def get_username(self, obj):
        return obj.user.username if obj.user else obj.phone
    
    def get_unread_count(self, obj):
        return obj.messages.filter(
            sender=SupportMessage.SENDER_USER,
            read=False
        ).count()
    
    def get_latest_message(self, obj):
        msg = obj.messages.order_by('-created_at').first()
        return msg.content[:100] if msg else ""
    
    def get_latest_time(self, obj):
        msg = obj.messages.order_by('-created_at').first()
        return msg.created_at.isoformat() if msg else None


class SupportTicketDetailSerializer(serializers.ModelSerializer):
    """
    Full ticket info including all messages (agent detail view).
    """
    
    user = UserMinimalSerializer(read_only=True)
    messages = SupportMessageSerializer(many=True, read_only=True)
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    
    class Meta:
        model = SupportTicket
        fields = [
            'id',
            'user',
            'phone',
            'status',
            'status_display',
            'created_at',
            'messages',
        ]
        read_only_fields = fields


class SupportMessageCreateSerializer(serializers.Serializer):
    """
    Serializer for creating new messages.
    Used by both user and agent endpoints.
    """
    
    message = serializers.CharField(
        max_length=5000,
        min_length=1,
        trim_whitespace=True
    )
    
    def validate_message(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Message cannot be empty.")
        return value.strip()


class SupportConversationSerializer(serializers.ModelSerializer):
    """
    User's conversation view - their ticket + messages.
    """
    
    messages = SupportMessageSerializer(many=True, read_only=True)
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    
    class Meta:
        model = SupportTicket
        fields = [
            'id',
            'status',
            'status_display',
            'created_at',
            'messages',
        ]
        read_only_fields = fields


# -----------------------------------------------------------------------------
# Additional serializers for frontend integration
# -----------------------------------------------------------------------------

from ..models import FieldCard, Booking
from django.contrib.auth.models import User


class FieldCardSerializer(serializers.ModelSerializer):
    """Serializer for public field data."""
    amenities = serializers.SlugRelatedField(
        many=True,
        read_only=True,
        slug_field='name'
    )
    image_url = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    owner_id = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    reviewCount = serializers.SerializerMethodField()
    userHasReviewed = serializers.SerializerMethodField()
    pricePerHour = serializers.IntegerField(source='price_per_hour', read_only=True)
    length = serializers.IntegerField(source='length_m', read_only=True)
    width = serializers.IntegerField(source='width_m', read_only=True)

    class Meta:
        model = FieldCard
        fields = [
            'id',
            'name',
            'city',
            'district',
            'address',
            'description',
            'pricePerHour',
            'length',
            'width',
            'image_url',
            'images',
            'amenities',
            'owner_id',
            'status',
            'status_display',
            'rating',
            'reviewCount',
            'userHasReviewed',
        ]
        read_only_fields = fields

    def get_owner_id(self, obj):
        return obj.owner_id if obj.owner else None

    def get_images(self, obj):
        request = self.context.get('request')
        urls = []
        for image_obj in getattr(obj, 'images', []).all() if hasattr(obj, 'images') else []:
            try:
                url = image_obj.image.url
                urls.append(request.build_absolute_uri(url) if request else url)
            except Exception:
                continue
        return urls

    def get_status_display(self, obj):
        status_map = {
            'pending': 'Jarayonda',
            'approved': 'Qabul qilindi',
            'rejected': 'Taqiqlandi',
        }
        return status_map.get(obj.status, obj.status)

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image:
            try:
                # For uploaded ImageField files
                if hasattr(obj.image, 'url') and obj.image.name:
                    if obj.image.storage.exists(obj.image.name):
                        url = obj.image.url
                        return request.build_absolute_uri(url) if request else url
            except Exception:
                pass
        return None

    def get_rating(self, obj):
        avg_rating = obj.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(avg_rating, 1) if avg_rating is not None else 0

    def get_reviewCount(self, obj):
        return obj.reviews.count()

    def get_userHasReviewed(self, obj):
        request = self.context.get('request')
        if not request or not getattr(request, 'user', None) or not request.user.is_authenticated:
            return False
        return obj.reviews.filter(user=request.user).exists()


class BookingSerializer(serializers.ModelSerializer):
    field = FieldCardSerializer(read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    verificationCode = serializers.CharField(source='verification_code', read_only=True)
    time = serializers.TimeField(source='start_time', read_only=True)
    duration = serializers.IntegerField(source='duration_hours', read_only=True)
    totalPrice = serializers.IntegerField(source='total_price', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id',
            'field',
            'user',
            'date',
            'start_time',
            'time',
            'duration_hours',
            'duration',
            'subtotal',
            'service_fee',
            'total_price',
            'totalPrice',
            'verification_code',
            'verificationCode',
            'created_at',
            'createdAt',
            'status',
        ]
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    profile_complete = serializers.SerializerMethodField()

    def get_profile_complete(self, obj):
        profile = getattr(obj, 'profile', None)
        return bool(
            obj.first_name and 
            obj.last_name and 
            profile and 
            profile.age is not None and 
            profile.user_type
        )

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'profile', 'profile_complete']
        read_only_fields = ['id', 'username']

