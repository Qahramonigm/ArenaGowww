"""
Payment System URL Configuration
Register payment API endpoints
"""
from django.urls import path
from . import payment_api

# API Endpoints
urlpatterns = [
    # Booking Management
    path('bookings/create/', payment_api.create_booking, name='create_booking'),
    path('bookings/<int:booking_id>/cancel/', payment_api.cancel_booking, name='cancel_booking'),
    
    # Payment Initiation & Status
    path('payments/initiate/', payment_api.initiate_payment, name='initiate_payment'),
    path('payments/<int:booking_id>/status/', payment_api.payment_status, name='payment_status'),
    
    # Payment Gateway Webhooks (must be public, no auth)
    path('webhooks/click/', payment_api.click_webhook, name='click_webhook'),
    path('webhooks/payme/', payment_api.payme_webhook, name='payme_webhook'),
    
    # Owner Wallet & Earnings
    path('owner/<int:owner_id>/wallet/', payment_api.owner_wallet, name='owner_wallet'),
    path('owner/<int:owner_id>/commissions/', payment_api.owner_commissions, name='owner_commissions'),
    path('owner/<int:owner_id>/stats/', payment_api.owner_earnings_stats, name='owner_stats'),
    
    # Admin Analytics
    path('admin/analytics/', payment_api.platform_analytics, name='platform_analytics'),
]
