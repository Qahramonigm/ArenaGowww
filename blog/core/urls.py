from django.urls import path, include
from django.views.generic import TemplateView
from . import views

urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="index"),
    # core API and feature routes only; root path is no longer exposed
    path("owner/fields/create/", views.owner_create_field),
    path("owner/fields/", views.owner_my_fields),

    path(
        "owner/bookings/<int:booking_id>/verify/",
        views.verify_booking_code,
        name="verify_booking"
    ),
    path("bookings/create/", views.create_booking, name="create_booking"),
    path(
        "fields/<int:field_id>/slots/",
        views.field_available_slots,
        name="field_slots"
    ),
    path("bookings/my/", views.my_bookings, name="my_bookings"),
    path("bookings/<int:booking_id>/cancel/", views.cancel_booking, name="cancel_booking"),
    path("owner/bookings/", views.owner_bookings),
    path(
        "owner/bookings/<int:booking_id>/complete/",
        views.complete_booking
    ),
    path("payment/click/webhook/", views.click_webhook),
    # support frontend page (requires login)
    path("support/", views.support_page, name="support_page"),
    # API endpoints
    path("support/messages/", views.support_conversation, name="support_conversation"),
    path("support/send/", views.support_send, name="support_send"),
    path("support/info/", views.support_info, name="support_info"),
    # support agent panel
    path("support/agent/login/", views.support_agent_login, name="support_agent_login"),
    path("support/agent/logout/", views.support_agent_logout, name="support_agent_logout"),
    path("support/agent/", views.support_agent_panel, name="support_agent_panel"),
    path("support/agent/reply/<int:ticket_id>/", views.support_agent_reply, name="support_agent_reply"),
    path("support/agent/api/tickets/", views.support_agent_api_tickets, name="support_agent_api_tickets"),
    path("support/agent/api/conversation/<int:ticket_id>/", views.support_agent_conversation, name="support_agent_conversation"),
    # Admin stats dashboard
    path("admin/stats/", views.admin_stats, name="admin_stats"),
    # manual test page removed in production (see commit history)
    # path("test/endpoints/", TemplateView.as_view(template_name="test_endpoints.html"), name="test_endpoints"),
    
    # Include the new RESTful API with v1 versioning
    path("api/", include("core.api.urls")),
]
















