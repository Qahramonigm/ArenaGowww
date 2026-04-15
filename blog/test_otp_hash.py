#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings')
django.setup()

from core.models import OTPCode
from django.contrib.auth.hashers import check_password

print("\n" + "="*60)
print("TESTING OTP CODE VERIFICATION")
print("="*60 + "\n")

# Get the latest OTP
otp = OTPCode.objects.filter(phone='+998200005452').order_by('-created_at').first()

if not otp:
    print("❌ No OTP found for +998200005452")
    exit(1)

print(f"OTP ID: {otp.id}")
print(f"Phone: {otp.phone}")
print(f"Hash exists: {bool(otp.code_hash)} (length: {len(otp.code_hash) if otp.code_hash else 0})")
print(f"Attempts: {otp.attempts}/{otp.max_attempts}")
print()

# Test the code
test_codes = [
    "464745",   # The code user entered
    "464745\n",  # With newline  
    " 464745",  # With space
    "464745 ",  # Trailing space
]

print("Testing codes:")
for code in test_codes:
    try:
        result = check_password(code, otp.code_hash)
        status = "✅ MATCH!" if result else "❌ NO MATCH"
        print(f"  {status} - Code: '{code}' (repr: {repr(code)})")
    except Exception as e:
        print(f"  ❌ ERROR - Code: '{code}' - {type(e).__name__}: {e}")

print("\n" + "="*60)
print("NOTE: If none of the codes match, the hash was created incorrectly")
print("when the OTP was first generated.")
print("="*60)
