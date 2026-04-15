"""Test owner booking block"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings')
sys.path.insert(0, '/'.join(os.path.dirname(__file__).split('\\')[:-1]))
django.setup()

from django.test import TestCase, Client
from django.contrib.auth.models import User
from core.models import FieldCard, FieldStatus, UserTicket
from rest_framework_simplejwt.tokens import RefreshToken

class OwnerBookingBlockTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.regular_user = User.objects.create_user(username='regularuser', password='pass123')
        self.owner_user = User.objects.create_user(username='owneruser', password='pass123')
        
        # Create UserTicket for regular user
        self.user_ticket, created = UserTicket.objects.get_or_create(
            user=self.regular_user,
            defaults={
                'tickets_ten': 5,
                'tickets_twenty': 3,
                'tickets_fifty': 2,
                'tickets_free': 1
            }
        )
        if not created:
            # Update existing
            self.user_ticket.tickets_ten = 5
            self.user_ticket.tickets_twenty = 3
            self.user_ticket.tickets_fifty = 2
            self.user_ticket.tickets_free = 1
            self.user_ticket.save()
        
        self.field = FieldCard.objects.create(
            owner=self.owner_user,
            name='Test Field',
            city='Test City',
            district='Test',
            price_per_hour=50000,
            status=FieldStatus.APPROVED
        )
        
    def test_regular_user_can_book(self):
        """Regular users should be able to make bookings"""
        # Get token for regular user
        refresh = RefreshToken.for_user(self.regular_user)
        token = str(refresh.access_token)
        
        response = self.client.post(
            '/api/bookings/',
            {
                'fieldId': self.field.id,
                'date': '2026-04-15',
                'time': '10:00',
                'duration': 1
            },
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        
        # Should either succeed (201) or fail with different error, not 403
        print(f"Regular user booking: {response.status_code}")
        self.assertNotEqual(response.status_code, 403)
        
    def test_owner_cannot_book(self):
        """Field owners should NOT be able to make bookings"""
        # Get token for owner
        refresh = RefreshToken.for_user(self.owner_user)
        token = str(refresh.access_token)
        
        response = self.client.post(
            '/api/bookings/',
            {
                'fieldId': 999,  # Any field
                'date': '2026-04-15',
                'time': '10:00',
                'duration': 1
            },
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        
        # Should return 403 Forbidden
        print(f"Owner booking attempt: {response.status_code}")
        self.assertEqual(response.status_code, 403)
        
        data = response.json()
        self.assertIn('detail', data)
        self.assertIn('cannot make bookings', data['detail'].lower())

    def test_ticket_decrement_on_booking(self):
        """Test that tickets are decremented when used in booking"""
        # Get token for regular user
        refresh = RefreshToken.for_user(self.regular_user)
        token = str(refresh.access_token)
        
        # Check initial ticket count
        initial_ten = self.user_ticket.tickets_ten
        self.assertEqual(initial_ten, 5)
        
        # Book with 10% ticket
        response = self.client.post(
            '/api/bookings/',
            {
                'field_id': self.field.id,
                'date': '2026-04-15',
                'start_time': '10:00',
                'duration_hours': 1,
                'ticket': 'ten'
            },
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        
        print(f"Ticket booking response: {response.status_code}")
        if response.status_code != 201:
            print(f"Response data: {response.json()}")
        
        self.assertEqual(response.status_code, 201)
        
        # Refresh user ticket from database
        self.user_ticket.refresh_from_db()
        
        # Check that ticket count decreased
        self.assertEqual(self.user_ticket.tickets_ten, initial_ten - 1)
        print(f"Tickets decreased: {initial_ten} -> {self.user_ticket.tickets_ten}")
        
        # Check response includes updated ticket counts
        data = response.json()
        self.assertIn('ticketCounts', data)
        self.assertEqual(data['ticketCounts']['ten'], initial_ten - 1)

if __name__ == '__main__':
    import unittest
    unittest.main()
