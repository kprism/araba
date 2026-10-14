from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import Business, BusinessFact


class SelectedBusinessVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.one = Business.objects.create(
            identity_key="1" * 64, name="테스트식당1",
            normalized_name="테스트식당1", address="창원시 북면",
        )
        self.two = Business.objects.create(
            identity_key="2" * 64, name="테스트식당2",
            normalized_name="테스트식당2", address="창원시 북면",
        )
        self.three = Business.objects.create(
            identity_key="3" * 64, name="테스트식당3",
            normalized_name="테스트식당3", address="창원시 북면",
        )
        self.fact = BusinessFact.objects.create(
            business=self.one, key="parking_available",
            source="business_official", value={"value": True},
        )
        User = get_user_model()
        self.admin = User.objects.create_user("real_staff", password="SomeStrongPass91!", is_staff=True)
        self.other = User.objects.create_user("merchant_user", password="SomeStrongPass91!")
        self.staff_token = Token.objects.create(user=self.admin)
        self.other_token = Token.objects.create(user=self.other)
        self.url = "/api/admin/businesses/visibility/"

    def _post(self, ids, active=False, confirmation="SELECTED_ONLY"):
        return self.client.post(
            self.url,
            {"ids": ids, "active": active, "confirmation": confirmation},
            format="json",
        )

    def test_public_or_merchant_cannot_hide_business(self):
        self.assertIn(self._post([self.one.pk]).status_code, (401, 403))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.other_token.key}")
        self.assertEqual(self._post([self.one.pk]).status_code, 403)
        self.assertEqual(Business.objects.filter(active=True).count(), 3)

    def test_only_checked_ids_hidden_unchecked_remain_and_facts_remain(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token.key}")
        response = self._post([self.one.pk, self.three.pk])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["changed"], 2)
        self.one.refresh_from_db()
        self.two.refresh_from_db()
        self.three.refresh_from_db()
        self.assertFalse(self.one.active)
        self.assertTrue(self.two.active)
        self.assertFalse(self.three.active)
        self.assertEqual(Business.objects.count(), 3)
        self.assertTrue(BusinessFact.objects.filter(pk=self.fact.pk).exists())
        audit = self.one.source_meta["admin_visibility_history"]
        self.assertEqual(audit[-1]["admin_user_id"], self.admin.pk)
        self.assertFalse(audit[-1]["to_active"])
        active = self.client.get("/api/admin/businesses/", {"active": "active"})
        self.assertEqual(active.data["filtered_count"], 1)
        inactive = self.client.get("/api/admin/businesses/", {"active": "inactive"})
        self.assertEqual(inactive.data["filtered_count"], 2)

    def test_admin_can_restore_only_chosen_inactive_business(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token.key}")
        self._post([self.one.pk, self.three.pk])
        r = self._post([self.one.pk], active=True)
        self.assertEqual(r.status_code, 200, r.data)
        self.one.refresh_from_db()
        self.three.refresh_from_db()
        self.assertTrue(self.one.active)
        self.assertFalse(self.three.active)

    def test_missing_id_makes_transaction_fail_without_other_changes(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token.key}")
        result = self._post([self.one.pk, 999999])
        self.assertEqual(result.status_code, 404)
        self.one.refresh_from_db()
        self.assertTrue(self.one.active)

    def test_bulk_filter_without_selected_ids_is_not_supported(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token.key}")
        for ids in ([], ["1"], [self.one.pk, self.one.pk], [True]):
            self.assertEqual(self._post(ids).status_code, 400)
        self.assertEqual(self._post([self.one.pk], confirmation="").status_code, 400)
        self.assertEqual(Business.objects.filter(active=True).count(), 3)

    def test_non_approved_admin_account_cannot_escalate_by_client_role(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.other_token.key}")
        result = self.client.post(self.url, {
            "ids": [self.one.pk],
            "active": False,
            "confirmation": "SELECTED_ONLY",
            "role": "administrator",
        }, format="json")
        self.assertEqual(result.status_code, 403)
        self.one.refresh_from_db()
        self.assertTrue(self.one.active)
