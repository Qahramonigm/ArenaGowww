from django.test import TestCase, Client
from rest_framework.test import APITestCase, APIClient
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from ..models import OTPCode, UserProfile
from django.utils import timezone
from datetime import timedelta
from django.urls import reverse
import json


class OTPAuthTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_request_and_verify_otp_creates_or_reuses_user(self):
        phone = '+998901234567'
        # request otp - for side effects and OTP row creation
        resp = self.client.post(reverse('api:api-request-otp'), {'phone': phone})
        self.assertEqual(resp.status_code, 200)
        otp = OTPCode.objects.filter(phone=phone).order_by('-created_at').first()
        self.assertIsNotNone(otp)

        # Force known code for reliable unit testing
        code = '123456'
        otp.code_hash = make_password(code)
        otp.expires_at = timezone.now() + timedelta(minutes=3)
        otp.is_used = False
        otp.attempts = 0
        otp.save()

        resp2 = self.client.post(reverse('api:api-verify-code'), {'phone': phone, 'code': code})
        self.assertEqual(resp2.status_code, 200)

        user = User.objects.filter(profile__phone=phone).first()
        self.assertIsNotNone(user)

    def test_request_and_verify_otp_creates_user_with_email(self):
        email = 'testuser@example.com'
        resp = self.client.post(reverse('api:api-request-otp'), {'email': email})
        self.assertEqual(resp.status_code, 200)

        otp = OTPCode.objects.filter(phone=email).order_by('-created_at').first()
        self.assertIsNotNone(otp)

        code = '654321'
        otp.code_hash = make_password(code)
        otp.expires_at = timezone.now() + timedelta(minutes=3)
        otp.is_used = False
        otp.attempts = 0
        otp.save()

        resp2 = self.client.post(reverse('api:api-verify-code'), {'email': email, 'code': code})
        self.assertEqual(resp2.status_code, 200)

        user = User.objects.filter(profile__phone=email).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.email, email)

        # OTP email + welcome on verify
        from django.core import mail
        self.assertEqual(len(mail.outbox), 2)

        # first email is OTP, second is welcome
        self.assertIn('ArenaGo', mail.outbox[0].subject)
        self.assertIn('Salom', mail.outbox[0].body)
        self.assertIn('ArenaGo', mail.outbox[1].subject)
        self.assertIn('Salom', mail.outbox[1].body)

    def test_phone_reuse_logs_into_existing_user(self):
        phone = '+998912345678'
        user0 = User.objects.create(username='u_existing')
        profile, created = UserProfile.objects.get_or_create(user=user0, defaults={'phone': phone, 'user_type': 'user'})
        if not created:
            profile.phone = phone
            profile.user_type = 'user'
            profile.save(update_fields=['phone', 'user_type'])

        resp = self.client.post(reverse('api:api-request-otp'), {'phone': phone})
        self.assertEqual(resp.status_code, 200)

        otp = OTPCode.objects.filter(phone=phone).order_by('-created_at').first()
        self.assertIsNotNone(otp)

        code = '111222'
        otp.code_hash = make_password(code)
        otp.expires_at = timezone.now() + timedelta(minutes=3)
        otp.is_used = False
        otp.attempts = 0
        otp.save()

        resp2 = self.client.post(reverse('api:api-verify-code'), {'phone': phone, 'code': code}, format='json')
        self.assertEqual(resp2.status_code, 200)

        user_after = User.objects.filter(profile__phone=phone).first()
        self.assertEqual(user_after.id, user0.id)

    def test_otp_wrong_attempts_locked(self):
        phone = '+998931234567'
        # request otp
        self.client.post(reverse('api:api-request-otp'), {'phone': phone})
        otp = OTPCode.objects.filter(phone=phone).order_by('-created_at').first()
        self.assertIsNotNone(otp)
        # submit wrong code max_attempts times
        for i in range(otp.max_attempts):
            resp = self.client.post(reverse('api:api-verify-code'), {'phone': phone, 'code': '000000'})
            # first (max_attempts-1) should be 400, last should be 429
            if i < otp.max_attempts - 1:
                self.assertEqual(resp.status_code, 400)
            else:
                self.assertIn(resp.status_code, (400, 429))

    def test_otp_expiry(self):
        phone = '+998941234567'
        # create expired OTP with hashed code
        expired = OTPCode.objects.create(
            phone=phone,
            code_hash=make_password('123456'),
            expires_at=timezone.now() - timedelta(minutes=1),
            is_used=False,
            attempts=0,
        )
        resp = self.client.post(reverse('api:api-verify-code'), {'phone': phone, 'code': '123456'})
        self.assertEqual(resp.status_code, 400)
