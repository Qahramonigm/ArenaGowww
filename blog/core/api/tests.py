"""
API Tests for Support System Endpoints.
Tests both agent and user endpoints to ensure proper functionality.
Uses Django test client with JSON responses.
"""
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from ..models import SupportTicket, SupportMessage, UserType


class SupportAPIBaseTest(TestCase):
    """Base test case with fixtures."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        
        # Create users
        self.user1 = User.objects.create_user(username='alice', password='secret', email='alice@example.com')
        self.user2 = User.objects.create_user(username='bob', password='secret', email='bob@example.com')
        
        # Create support agent
        support_group, _ = Group.objects.get_or_create(name='support')
        self.agent = User.objects.create_user(username='agent1', password='secret', email='agent1@example.com')
        self.agent.groups.add(support_group)
        
        # Create tickets
        self.ticket1 = SupportTicket.objects.create(user=self.user1, phone='+998123')
        self.ticket2 = SupportTicket.objects.create(user=self.user2, phone='+998456')
        
        # Add messages
        SupportMessage.objects.create(
            ticket=self.ticket1,
            sender=SupportMessage.SENDER_USER,
            content='Hello'
        )
        SupportMessage.objects.create(
            ticket=self.ticket1,
            sender=SupportMessage.SENDER_SUPPORT,
            content='Help message',
            agent=self.agent
        )
    
    def _parse_json(self, response):
        """Parse JSON response content."""
        try:
            return json.loads(response.content.decode())
        except:
            return None


class AgentTicketsListTest(SupportAPIBaseTest):
    """Test /api/v1/support/tickets/ endpoint."""
    
    def test_agent_can_list_all_tickets(self):
        """Agent can list all tickets."""
        self.client.login(username='agent1', password='secret')
        response = self.client.get('/api/v1/support/tickets/', HTTP_ACCEPT='application/json; version=1.0')
        
        self.assertEqual(response.status_code, 200)
        data = self._parse_json(response)
        self.assertIsNotNone(data)
        self.assertEqual(data['count'], 2)
    
    def test_non_agent_blocked_from_list(self):
        """Non-agent gets 403."""
        self.client.login(username='alice', password='secret')
        response = self.client.get('/api/v1/support/tickets/', HTTP_ACCEPT='application/json; version=1.0')
        
        self.assertEqual(response.status_code, 403)
    
    def test_anonymous_blocked_from_list(self):
        """Anonymous user gets 401."""
        response = self.client.get('/api/v1/support/tickets/', HTTP_ACCEPT='application/json; version=1.0')
        
        self.assertEqual(response.status_code, 401)


class AgentTicketDetailTest(SupportAPIBaseTest):
    """Test /api/v1/support/tickets/{id}/ endpoint."""
    
    def test_agent_can_view_ticket(self):
        """Agent can view ticket details."""
        self.client.login(username='agent1', password='secret')
        response = self.client.get(f'/api/v1/support/tickets/{self.ticket1.id}/', HTTP_ACCEPT='application/json; version=1.0')
        
        self.assertEqual(response.status_code, 200)
        data = self._parse_json(response)
        self.assertIsNotNone(data)
        self.assertIn('messages', data)
    
    def test_non_agent_blocked(self):
        """Non-agent gets 403."""
        self.client.login(username='alice', password='secret')
        response = self.client.get(f'/api/v1/support/tickets/{self.ticket1.id}/', HTTP_ACCEPT='application/json; version=1.0')
        
        self.assertEqual(response.status_code, 403)


class AgentReplyTest(SupportAPIBaseTest):
    """Test /api/v1/support/tickets/{id}/reply/ endpoint."""
    
    def test_agent_can_reply(self):
        """Agent can send reply."""
        self.client.login(username='agent1', password='secret')
        response = self.client.post(
            f'/api/v1/support/tickets/{self.ticket1.id}/reply/',
            json.dumps({'message': 'Reply'}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        
        self.assertEqual(response.status_code, 201)
        data = self._parse_json(response)
        self.assertIsNotNone(data)
        self.assertIn('id', data)
    
    def test_non_agent_blocked(self):
        """Non-agent gets 403."""
        self.client.login(username='alice', password='secret')
        response = self.client.post(
            f'/api/v1/support/tickets/{self.ticket1.id}/reply/',
            json.dumps({'message': 'Reply'}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        
        self.assertEqual(response.status_code, 403)


class UserConversationTest(SupportAPIBaseTest):
    """Test /api/v1/support/conversations/ endpoint."""
    
    def test_user_can_view_conversation(self):
        """User can view their conversation."""
        self.client.login(username='alice', password='secret')
        response = self.client.get('/api/v1/support/conversations/', HTTP_ACCEPT='application/json; version=1.0')
        
        self.assertEqual(response.status_code, 200)
        data = self._parse_json(response)
        self.assertIsNotNone(data)
    
    def test_user_without_ticket_gets_empty(self):
        """User without ticket sees empty messages."""
        user3 = User.objects.create_user(username='charlie', password='secret', email='charlie@example.com')
        self.client.login(username='charlie', password='secret')
        response = self.client.get('/api/v1/support/conversations/', HTTP_ACCEPT='application/json; version=1.0')
        
        self.assertEqual(response.status_code, 200)
        data = self._parse_json(response)
        self.assertEqual(data['messages'], [])
    
    def test_anonymous_blocked(self):
        """Anonymous user gets 401."""
        response = self.client.get('/api/v1/support/conversations/', HTTP_ACCEPT='application/json; version=1.0')
        
        self.assertEqual(response.status_code, 401)


class UserSendMessageTest(SupportAPIBaseTest):
    """Test /api/v1/support/messages/ endpoint."""
    
    def test_user_can_send_message(self):
        """User can send message."""
        user3 = User.objects.create_user(username='charlie', password='secret', email='charlie@example.com')
        self.client.login(username='charlie', password='secret')
        response = self.client.post(
            '/api/v1/support/messages/',
            json.dumps({'message': 'question'}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        
        self.assertEqual(response.status_code, 201)
        data = self._parse_json(response)
        self.assertIsNotNone(data)
    
    def test_message_creates_ticket(self):
        """Message creates ticket if needed."""
        user3 = User.objects.create_user(username='charlie', password='secret', email='charlie@example.com')
        self.client.login(username='charlie', password='secret')
        self.client.post(
            '/api/v1/support/messages/',
            json.dumps({'message': 'q'}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        
        ticket = SupportTicket.objects.filter(user=user3).first()
        self.assertIsNotNone(ticket)
    
    def test_anonymous_blocked(self):
        """Anonymous user gets 401."""
        response = self.client.post(
            '/api/v1/support/messages/',
            json.dumps({'message': 'test'}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )         
        self.assertEqual(response.status_code, 401)


from ..models import FieldCard, FieldStatus, Booking, BookingStatus


class TicketShopConfigTest(SupportAPIBaseTest):
    """Test /api/ticket-shop/ configuration endpoint."""

    def test_ticket_shop_config_returns_default_values(self):
        response = self.client.get('/api/ticket-shop/', HTTP_ACCEPT='application/json; version=1.0')
        self.assertEqual(response.status_code, 200)
        data = self._parse_json(response)
        self.assertIsNotNone(data)
        self.assertIn('tickets', data)
        self.assertEqual(len(data['tickets']), 4)
        self.assertIn('price_coins', data['tickets'][0])


class FieldSlotsTest(SupportAPIBaseTest):
    """Test /api/fields/<id>/slots/ endpoint."""

    def setUp(self):
        super().setUp()
        self.field = FieldCard.objects.create(
            owner=self.user1,
            name='Slot Field',
            city='City',
            district='District',
            address='Address',
            description='A field for slots',
            price_per_hour=1000,
            image='fields/test.png',
        )

    def test_field_slots_endpoint_returns_slots(self):
        self.client.login(username='alice', password='secret')
        date = '2026-03-29'
        response = self.client.get(
            f'/api/fields/{self.field.id}/slots/?date={date}',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        self.assertEqual(response.status_code, 200)
        data = self._parse_json(response)
        self.assertIsNotNone(data)
        self.assertIn('slots', data)
        self.assertTrue(isinstance(data['slots'], list))
        self.assertGreaterEqual(len(data['slots']), 1)
        self.assertEqual(data['slots'][0]['start_time'], '08:00')


class VerifyBookingTest(SupportAPIBaseTest):
    """Tests for /api/owner/<owner_id>/bookings/<booking_id>/verify/ endpoint."""

    def setUp(self):
        super().setUp()
        self.owner = self.user1
        self.owner.profile.user_type = UserType.OWNER
        self.owner.profile.save()
        self.other_user = self.user2
        self.field = FieldCard.objects.create(
            owner=self.owner,
            name='Test Field',
            city='Test City',
            district='Test District',
            address='123 Test St',
            description='Test field',
            price_per_hour=1000,
            image='fields/test.png',
        )
        self.booking = Booking.objects.create(
            field=self.field,
            user=self.other_user,
            date='2025-01-01',
            start_time='12:00',
            duration_hours=1,
        )

    def test_owner_can_verify_booking_with_valid_code(self):
        self.client.login(username='alice', password='secret')
        response = self.client.post(
            f'/api/owner/{self.owner.id}/bookings/{self.booking.id}/verify/',
            json.dumps({'verificationCode': self.booking.verification_code}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        self.assertEqual(response.status_code, 200)
        data = self._parse_json(response)
        self.assertEqual(data.get('ok'), True)
        self.assertEqual(data.get('status'), BookingStatus.VERIFIED)

    def test_owner_cannot_verify_already_verified_booking(self):
        # First, verify the booking
        self.booking.status = BookingStatus.VERIFIED
        self.booking.save()
        
        self.client.login(username='alice', password='secret')
        response = self.client.post(
            f'/api/owner/{self.owner.id}/bookings/{self.booking.id}/verify/',
            json.dumps({'verificationCode': self.booking.verification_code}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        self.assertEqual(response.status_code, 400)
        data = self._parse_json(response)
        self.assertEqual(data.get('ok'), False)
        self.assertIn('allaqachon tasdiqlangan', data.get('error', ''))

    def test_owner_gets_400_if_code_missing(self):
        self.client.login(username='alice', password='secret')
        response = self.client.post(
            f'/api/owner/{self.owner.id}/bookings/{self.booking.id}/verify/',
            json.dumps({}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        self.assertEqual(response.status_code, 400)

    def test_owner_gets_400_if_code_incorrect(self):
        self.client.login(username='alice', password='secret')
        response = self.client.post(
            f'/api/owner/{self.owner.id}/bookings/{self.booking.id}/verify/',
            json.dumps({'verificationCode': '000'}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        self.assertEqual(response.status_code, 400)


class FieldRatingTest(SupportAPIBaseTest):
    def setUp(self):
        super().setUp()
        self.field = FieldCard.objects.create(
            owner=self.user1,
            name='Rating Test',
            city='Test City',
            district='Test District',
            address='123 Test St',
            description='Test field for ratings',
            price_per_hour=1000,
            image='fields/test.png',
            status=FieldStatus.APPROVED,
        )

    def test_user_can_submit_one_rating_only(self):
        self.client.login(username='alice', password='secret')

        response = self.client.post(
            f'/api/fields/{self.field.id}/ratings/',
            json.dumps({'rating': 5, 'comment': 'Great!', 'userId': self.user1.id}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            f'/api/fields/{self.field.id}/ratings/',
            json.dumps({'rating': 4, 'comment': 'Update', 'userId': self.user1.id}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )
        self.assertEqual(response.status_code, 400)

    def test_field_rating_aggregation_increments_gradually(self):
        self.client.login(username='alice', password='secret')
        self.client.post(
            f'/api/fields/{self.field.id}/ratings/',
            json.dumps({'rating': 4, 'comment': 'Good', 'userId': self.user1.id}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )

        self.client.logout()
        self.client.login(username='bob', password='secret')
        self.client.post(
            f'/api/fields/{self.field.id}/ratings/',
            json.dumps({'rating': 2, 'comment': 'Ok', 'userId': self.user2.id}),
            content_type='application/json',
            HTTP_ACCEPT='application/json; version=1.0'
        )

        response = self.client.get(f'/api/fields/{self.field.id}/', HTTP_ACCEPT='application/json; version=1.0')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode())
        self.assertEqual(data.get('reviewCount'), 2)
        self.assertEqual(data.get('rating'), 3.0)
        self.assertTrue(data.get('userHasReviewed'))
