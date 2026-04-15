#!/usr/bin/env python
import os
import django
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings')
django.setup()

from core.models import OTPCode
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from datetime import timedelta

print("\n" + "="*60)
print("CREATING FRESH TEST OTP")
print("="*60 + "\n")

# Delete old test OTPs
OTPCode.objects.filter(phone='+998200005452').delete()

# Generate a new code
code = f"{random.randint(0, 999999):06d}"
code_hash = make_password(code)

print(f"Generated code: {code}")
print(f"Code hash: {code_hash[:50]}...")
print(f"Hash length: {len(code_hash)}")
print()

# Create in DB
now = timezone.now()
expires = now + timedelta(minutes=3)
otp = OTPCode.objects.create(
    phone='+998200005452',
    code_hash=code_hash,
    expires_at=expires
)

print(f"✅ OTP Created in database:")
print(f"  ID: {otp.id}")
print(f"  Phone: {otp.phone}")
print(f"  Expires in: 3 minutes")
print()

# Test immediately
test_result = check_password(code, code_hash)
print(f"Verification test (should be True): {test_result}")
print()

print("="*60)
print("NEXT STEPS:")
print("="*60)
print()
print("1. GO TO SMS and check what code you received for +998200005452")
print(f"   (The code we just generated and hashed is: {code})")
print()
print("2. If SMS shows different code, reply with that code")
print()
print("3. If SMS shows same code ({code}), try entering it in the app")
print()
