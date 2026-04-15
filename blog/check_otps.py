#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings')
django.setup()

from core.models import OTPCode
from django.utils import timezone

print("\n" + "="*60)
print("CHECKING OTP DATABASE")
print("="*60 + "\n")

now = timezone.now()
all_otps = OTPCode.objects.all().order_by('-created_at')

if not all_otps.exists():
    print("❌ NO OTP CODES IN DATABASE!")
    print("\nMake sure you:")
    print("1. Requested OTP first (should show SMS code)")
    print("2. Check that request succeeded (should see 'SMS kod yuborildi!')")
    exit(0)

print(f"Total OTP codes in DB: {all_otps.count()}\n")

for otp in all_otps[:10]:  # Show latest 10
    time_diff = now - otp.created_at
    expires_in = otp.expires_at - now
    
    print(f"ID: {otp.id}")
    print(f"  Phone: '{otp.phone}'")
    print(f"  Is Used: {otp.is_used}")
    print(f"  Attempts: {otp.attempts}/{otp.max_attempts}")
    print(f"  Created: {otp.created_at} ({time_diff.total_seconds():.0f}s ago)")
    print(f"  Expires: {otp.expires_at} (in {expires_in.total_seconds():.0f}s)")
    print(f"  Hash exists: {bool(otp.code_hash)}")
    print(f"  Hash length: {len(otp.code_hash) if otp.code_hash else 0}")
    print()

# Check if the phone from frontend exists
target_phone = "+998200005452"
print(f"\n{'='*60}")
print(f"SEARCHING FOR PHONE: '{target_phone}'")
print(f"{'='*60}\n")

matching = OTPCode.objects.filter(phone=target_phone)
if matching.exists():
    print(f"✅ Found {matching.count()} OTP(s) for this phone!")
    for otp in matching:
        print(f"  - ID {otp.id}: used={otp.is_used}, expired={otp.expires_at <= now}")
else:
    print(f"❌ NO OTP found for '{target_phone}'")
    print(f"\nAvailable phones in DB:")
    phones = OTPCode.objects.values_list('phone', flat=True).distinct()
    for phone in phones:
        print(f"  - '{phone}'")
