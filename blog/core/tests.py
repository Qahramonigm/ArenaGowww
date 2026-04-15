from django.test import TestCase, Client
from django.contrib.auth.models import User
from .models import SupportTicket, SupportMessage, FieldCard, OwnerCard


class SupportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="alice", password="secret")
        # create a support group so we can log in as an agent later
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name="support")

    def test_empty_conversation(self):
        self.client.login(username="alice", password="secret")
        resp = self.client.get("/support/messages/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["messages"], [])

    def test_send_message_creates_ticket(self):
        self.client.login(username="alice", password="secret")
        resp = self.client.post(
            "/support/send/",
            data={"message": "hello"},
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        ticket = SupportTicket.objects.get(user=self.user)
        self.assertEqual(ticket.messages.count(), 1)
        msg = ticket.messages.first()
        self.assertEqual(msg.content, "hello")
        self.assertEqual(msg.sender, SupportMessage.SENDER_USER)

    def test_conversation_returns_messages(self):
        ticket = SupportTicket.objects.create(user=self.user)
        SupportMessage.objects.create(ticket=ticket, content="hi user")
        self.client.login(username="alice", password="secret")
        resp = self.client.get("/support/messages/")
        data = resp.json()
        self.assertIn("hi user", data["messages"][0]["content"])

    def test_support_info(self):
        self.client.login(username="alice", password="secret")
        resp = self.client.get("/support/info/")
        self.assertEqual(resp.status_code, 200)
        info = resp.json()
        self.assertIn("email", info)
        self.assertIn("phone", info)

    def test_support_page_requires_login(self):
        # anonymous should be redirected (login required)
        resp = self.client.get("/support/")
        self.assertNotEqual(resp.status_code, 200)

    def test_support_page_renders_for_user(self):
        self.client.login(username="alice", password="secret")
        resp = self.client.get("/support/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Support", resp.content)

    def test_index_page_shows_links(self):
        # index should load anonymously and contain navigation
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Welcome to ArenaGo", resp.content)
        # should include our quick nav links
        self.assertIn(b"/support/", resp.content)
        self.assertIn(b"/bookings/my/", resp.content)

    def test_owner_card_crud_and_field_requirement(self):
        self.client.login(username="alice", password="secret")
        uid = self.user.id

        # No card yet
        resp = self.client.get(f"/api/owner/{uid}/card/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("hasCard"), False)

        # Trying to create field without card must fail
        resp = self.client.post(f"/api/owner/{uid}/fields/", data={"name": "F1", "city": "Tashkent", "address": "A street", "description": "desc", "pricePerHour": 50000}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('error'), 'no_card')

        # Add card
        resp = self.client.post(f"/api/owner/{uid}/card/", data={"cardNumber": "4111111111111111", "expiryDate": "12/28", "cvv": "123"}, content_type="application/json")
        self.assertEqual(resp.status_code, 201)

        # Duplicate add should fail
        resp = self.client.post(f"/api/owner/{uid}/card/", data={"cardNumber": "4111111111111111", "expiryDate": "12/28", "cvv": "123"}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)

        # Card is now present
        resp = self.client.get(f"/api/owner/{uid}/card/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("hasCard"), True)
        self.assertIn("cardNumber", resp.json())

        # Can create a field now
        resp = self.client.post(f"/api/owner/{uid}/fields/", data={"name": "F1", "city": "Tashkent", "address": "A street", "description": "desc", "pricePerHour": 50000}, content_type="application/json")
        self.assertEqual(resp.status_code, 201)

        # Delete card must fail now because an existing field exists
        resp = self.client.delete(f"/api/owner/{uid}/card/")
        self.assertEqual(resp.status_code, 400)

        # Update card should work
        resp = self.client.put(f"/api/owner/{uid}/card/", data={"cardNumber": "4012888888881881", "expiryDate": "01/30", "cvv": "321"}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)

        # Optional: delete card after deleting field
        fields_resp = self.client.get(f"/api/owner/{uid}/fields/")
        field_list = fields_resp.json()
        self.assertTrue(len(field_list) > 0)
        field_id = field_list[0]["id"]

        self.client.delete(f"/api/owner/{uid}/fields/{field_id}/")
        resp = self.client.delete(f"/api/owner/{uid}/card/")
        self.assertEqual(resp.status_code, 200)

    def test_owner_card_input_validation(self):
        self.client.login(username="alice", password="secret")
        uid = self.user.id

        # missing data
        resp = self.client.post(f"/api/owner/{uid}/card/", data={"cardNumber": "", "expiryDate": "", "cvv": ""}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('error'), 'invalid_card_data')

        # invalid format
        resp = self.client.post(f"/api/owner/{uid}/card/", data={"cardNumber": "1234", "expiryDate": "99/99", "cvv": "12"}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('error'), 'invalid_card_data')

        # invalid Luhn
        resp = self.client.post(f"/api/owner/{uid}/card/", data={"cardNumber": "4000000000000001", "expiryDate": "12/28", "cvv": "123"}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('error'), 'invalid_card_data')

        # valid card to make sure endpoint works
        resp = self.client.post(f"/api/owner/{uid}/card/", data={"cardNumber": "4111111111111111", "expiryDate": "12/28", "cvv": "123"}, content_type="application/json")
        self.assertEqual(resp.status_code, 201)

    def test_agent_api_tickets_sorted(self):
        # create two tickets with messages at different times and verify the
        # agent API returns them in newest‑first order
        from django.contrib.auth.models import Group
        agent = User.objects.create_user(username="bob", password="pw")
        # mark as support agent
        grp, _ = Group.objects.get_or_create(name="support")
        agent.groups.add(grp)

        # create tickets
        t1 = SupportTicket.objects.create(user=self.user)
        t2 = SupportTicket.objects.create(user=self.user, phone="+123")
        # older message on t1
        SupportMessage.objects.create(ticket=t1, sender=SupportMessage.SENDER_USER, content="old")
        # newer message on t2
        SupportMessage.objects.create(ticket=t2, sender=SupportMessage.SENDER_USER, content="new")

        # login as agent and call API
        self.client.force_login(agent)
        resp = self.client.get("/support/agent/api/tickets/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        ids = [t["id"] for t in data["tickets"]]
        # expect t2 (newer) first
        self.assertEqual(ids, [t2.id, t1.id])
