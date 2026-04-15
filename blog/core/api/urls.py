"""
API URL routes for v1 support endpoints.
"""
from django.urls import path
from . import views
from . import auth_views
from core.views import field_available_slots

app_name = 'api'

urlpatterns = [
    # ========== Public endpoints (frontend) ==========
    path('fields/', views.fields_list, name='fields-list'),
    path('fields/<int:field_id>/', views.field_detail, name='field-detail'),
    path('fields/<int:field_id>/ratings/', views.submit_field_rating, name='field-submit-rating'),
    path('fields/<int:field_id>/slots/', field_available_slots, name='field-slots'),
    path('bookings/', views.create_booking, name='api-create-booking'),
    path('bookings/<int:user_id>/', views.bookings_for_user, name='api-bookings-user'),
    path('auth/login/', views.auth_login, name='api-login'),
    path('auth/verify-code/', views.auth_verify_code, name='api-verify-code'),
    path('auth/request-otp/', views.request_otp, name='api-request-otp'),
    path('auth/me/', views.get_current_user, name='api-current-user'),
    path('auth/complete-profile/', views.complete_profile, name='api-complete-profile'),
    path('ticket-shop/', views.ticket_shop_config, name='api-ticket-shop'),
    # Token endpoints using cookies
    path("auth/token/", auth_views.token_obtain_pair_cookie, name="token_obtain_pair_cookie"),
    path("auth/token/refresh/", auth_views.token_refresh_cookie, name="token_refresh_cookie"),
    path("auth/logout/", auth_views.token_blacklist_cookie, name="token_blacklist_cookie"),
    path('users/<int:user_id>/', views.user_detail, name='api-user-detail'),
    # ========== Owner endpoints ==========
    path('owner/<int:owner_id>/fields/', views.owner_fields, name='api-owner-fields'),
    path('owner/<int:owner_id>/fields/<int:field_id>/', views.owner_field_detail, name='api-owner-field-detail'),
    path('owner/<int:owner_id>/bookings/', views.owner_bookings_api, name='api-owner-bookings'),
    path('owner/<int:owner_id>/bookings/<int:booking_id>/verify/', views.verify_booking, name='api-owner-verify-booking'),
    path('owner/<int:owner_id>/stats/', views.owner_stats, name='api-owner-stats'),
    path('owner/<int:owner_id>/fields/<int:field_id>/promote/', views.promote_field, name='api-owner-promote-field'),
    path('owner/<int:owner_id>/card/', views.owner_card, name='api-owner-card'),
    path('owner/<int:owner_id>/wallet/', views.owner_wallet, name='api-owner-wallet'),
    path('owner/<int:owner_id>/withdraw/', views.owner_withdraw, name='api-owner-withdraw'),

    # ========== Agent endpoints (support agents only) ==========
    path(
        'v1/support/tickets/',
        views.agent_tickets_list,
        name='agent-tickets-list'
    ),
    path(
        'v1/support/tickets/<int:ticket_id>/',
        views.agent_ticket_detail,
        name='agent-ticket-detail'
    ),
    path(
        'v1/support/tickets/<int:ticket_id>/reply/',
        views.agent_ticket_reply,
        name='agent-ticket-reply'
    ),

    # ========== User endpoints (authenticated users) ==========
    path(
        'v1/support/conversations/',
        views.user_conversation,
        name='user-conversation'
    ),
    path(
        'v1/support/messages/',
        views.user_send_message,
        name='user-send-message'
    ),

    # ========== Public endpoints ==========
    path(
        'v1/support/info/',
        views.support_info,
        name='support-info'
    ),
    # Support endpoints (for frontend)
    path('support/messages/', views.user_support_messages, name='api-support-messages'),
    path('support/send/', views.user_support_messages, name='api-support-send'),
    path('support/info/', views.support_info, name='api-support-info'),
]
