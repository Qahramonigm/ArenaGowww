#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings')
django.setup()

from core.models import OTPCode, SecurityIncident

# Clear all OTPs and security incidents
otp_count = OTPCode.objects.count()
incident_count = SecurityIncident.objects.count()

print(f"Clearing {otp_count} OTP codes...")
OTPCode.objects.all().delete()

print(f"Clearing {incident_count} security incidents...")
SecurityIncident.objects.all().delete()

print("✅ All test data cleared! You can now request OTP again.")
