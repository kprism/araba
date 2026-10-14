from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import Business, BusinessClaim, BusinessFact


class MerchantClaimPilotTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            provider="kakao",
            provider_place_id="existing-456",
            identity_key="a" * 64,
            name="순자네집밥",
            normalized_name="순자네집밥",
            category="음식점",
            address="경남 창원시 의창구 북면",
            phone="055-123-4567",
        )
        self.client = APIClient()

    def _register(self, name):
        response = self.client.post("/api/accounts/signup/", {
            "username": name,
            "password": "StrongTemporaryPassword72!",
            "password_confirm": "StrongTemporaryPassword72!",
            "terms_consent": True,
            "privacy_consent": True,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["token"]

    def _auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token)

    def _claim(self):
        return self.client.post("/api/merchant/claims/", {
            "business_id": self.business.pk,
            "owner_name": "김대표",
            "registration_number": "123-45-67890",
            "contact_phone": "010-1234-5678",
        }, format="json")

    def test_search_reuses_existing_business_without_creating_duplicate(self):
        response = self.client.get("/api/merchant/businesses/search/", {"q": "순자네"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["businesses"][0]["id"], self.business.pk)
        self.assertEqual(Business.objects.count(), 1)

    def test_requires_password_confirm_and_unique_id(self):
        r = self.client.post("/api/accounts/signup/", {
            "username": "merchant1", "password": "StrongTemporaryPassword72!",
            "password_confirm": "different",
            "terms_consent": True, "privacy_consent": True,
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self._register("merchant1")
        r = self.client.get("/api/accounts/username-available/", {"username": "MERCHANT1"})
        self.assertFalse(r.data["available"])
        r = self.client.post("/api/accounts/signup/", {
            "username": "merchant1", "password": "StrongTemporaryPassword72!",
            "password_confirm": "StrongTemporaryPassword72!",
            "terms_consent": True, "privacy_consent": True,
        }, format="json")
        self.assertEqual(r.status_code, 409)

    def test_unauthenticated_client_cannot_claim_or_edit(self):
        self.assertEqual(self._claim().status_code, 401)
        self.assertEqual(self.client.patch(
            "/api/merchant/claims/1/",
            {"extra_information": "malicious"}, format="json",
        ).status_code, 401)

    def test_pending_owner_draft_does_not_modify_existing_business(self):
        token = self._register("merchant2")
        self._auth(token)
        claimed = self._claim()
        self.assertEqual(claimed.status_code, 201, claimed.data)
        claim_id = claimed.data["claim"]["id"]
        claim = BusinessClaim.objects.get(pk=claim_id)
        self.assertNotIn("1234567890", str(claim.__dict__))
        r = self.client.patch(f"/api/merchant/claims/{claim_id}/", {
            "proposed_info": {"name": "순자네집밥 수정", "phone": "055-7777"},
            "extra_information": "예약 우선",
            "agent_instructions": "10% 초과 할인은 사람 승인",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["published"])
        self.business.refresh_from_db()
        self.assertEqual(self.business.name, "순자네집밥")
        self.assertEqual(BusinessFact.objects.count(), 0)
        self.assertEqual(Business.objects.count(), 1)

    def test_approved_claim_publishes_but_keeps_private_instructions_private(self):
        token = self._register("merchant3")
        self._auth(token)
        claim_id = self._claim().data["claim"]["id"]
        claim = BusinessClaim.objects.get(pk=claim_id)
        claim.status = BusinessClaim.STATUS_APPROVED
        claim.save(update_fields=["status"])
        r = self.client.patch(f"/api/merchant/claims/{claim_id}/", {
            "proposed_info": {
                "name": "순자네집밥 공식",
                "phone": "055-8888",
                "opening_hours": "매일 10:00~20:00",
            },
            "extra_information": "주차장 8대",
            "agent_instructions": "원가 아래 할인 금지; 외부 공개 금지",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["published"])
        self.business.refresh_from_db()
        self.assertEqual(self.business.name, "순자네집밥 공식")
        self.assertEqual(self.business.phone, "055-8888")
        self.assertIn("주차장 8대", str(self.business.snapshot))
        self.assertNotIn("원가 아래", str(self.business.snapshot))
        self.assertFalse(BusinessFact.objects.filter(key="agent_instructions").exists())

    def test_second_user_cannot_modify_first_users_claim(self):
        first = self._register("merchant4")
        self._auth(first)
        claim_id = self._claim().data["claim"]["id"]
        second = self._register("merchant5")
        self._auth(second)
        self.assertEqual(self.client.patch(
            f"/api/merchant/claims/{claim_id}/",
            {"extra_information": "타 업체 변경 시도"}, format="json",
        ).status_code, 404)
        self.assertEqual(self._claim().status_code, 201)  # pending duplicates require human review

    def test_already_verified_owner_blocks_new_ownership_claim(self):
        first = self._register("merchant6")
        self._auth(first)
        claim_id = self._claim().data["claim"]["id"]
        claim = BusinessClaim.objects.get(pk=claim_id)
        claim.status = BusinessClaim.STATUS_APPROVED
        claim.save(update_fields=["status"])
        second = self._register("merchant7")
        self._auth(second)
        self.assertEqual(self._claim().status_code, 409)

    def test_login_and_logout_token(self):
        token = self._register("merchant8")
        self.client.credentials()
        r = self.client.post("/api/accounts/login/", {
            "username": "merchant8",
            "password": "StrongTemporaryPassword72!",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["token"], token)
        self._auth(token)
        self.assertEqual(self.client.get("/api/accounts/me/").status_code, 200)
        self.assertEqual(self.client.post("/api/accounts/logout/").status_code, 200)
        self.assertEqual(self.client.get("/api/accounts/me/").status_code, 401)
