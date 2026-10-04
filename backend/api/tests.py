from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["service"],
            "ARABA API",
        )

    @patch(
        "api.views.get_openai_status",
        return_value={
            "configured": True,
            "masked": "sk-test••••••••••••1234",
        },
    )
    def test_openai_status_uses_request_key(
        self,
        mocked_status,
    ):
        response = self.client.get(
            "/api/settings/openai/",
            HTTP_X_OPENAI_API_KEY="sk-test-1234",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["configured"])
        mocked_status.assert_called_once_with(
            "sk-test-1234"
        )

    def test_openai_save_is_not_persisted_server_side(self):
        response = self.client.post(
            "/api/settings/openai/save/",
            {"api_key": "sk-test"},
            format="json",
        )

        self.assertEqual(response.status_code, 410)
        self.assertFalse(response.data["ok"])


class MissionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(
        "api.services.mission_service.create_mission"
    )
    def test_mission_create(
        self,
        mocked_create,
    ):
        mocked_create.return_value = {
            "title": "BMW X6 타이어 교체 알아보기",
            "summary": "창원에서 오늘 가능한 BMW X6 타이어 교체 업체를 가격 기준으로 비교",
            "category": "자동차",
            "location": "창원",
            "subject": "BMW X6 타이어 교체",
            "constraints": ["오늘 가능"],
            "comparison": "최저가격",
            "required_facts": [
                "업체명",
                "가격",
                "재고",
                "작업 가능시간",
            ],
            "needs_fresh_data": True,
            "may_need_phone_call": True,
            "missing_information": [],
            "clarification_questions": [],
            "ready_to_research": True,
        }

        response = self.client.post(
            "/api/missions/create/",
            {
                "request": (
                    "오늘 창원에서 BMW X6 타이어 "
                    "교체 가능한 가장 저렴한 곳 알아봐"
                )
            },
            format="json",
            HTTP_X_OPENAI_API_KEY="sk-test-1234",
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["mission"]["location"],
            "창원",
        )
        mocked_create.assert_called_once_with(
            "오늘 창원에서 BMW X6 타이어 교체 가능한 가장 저렴한 곳 알아봐",
            "sk-test-1234",
        )



class UpdateNotificationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_notify_update_requires_bearer_token(self):
        response = self.client.post(
            "/api/internal/notify-update/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["ok"])

    @patch(
        "api.services.update_notification_service."
        "send_update_notification",
        return_value="projects/araba-dev/messages/test",
    )
    @patch(
        "api.services.update_notification_service."
        "verify_github_actions_token",
        return_value={
            "repository": "kprism/araba",
            "ref": "refs/heads/main",
        },
    )
    def test_notify_update_sends_fcm_after_oidc_verification(
        self,
        mocked_verify,
        mocked_send,
    ):
        response = self.client.post(
            "/api/internal/notify-update/",
            {},
            format="json",
            HTTP_AUTHORIZATION="Bearer github-oidc-token",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        mocked_verify.assert_called_once_with(
            "github-oidc-token"
        )
        mocked_send.assert_called_once_with()



class NotificationRegistrationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(
        "api.services.update_notification_service."
        "subscribe_device_to_updates",
        return_value={
            "success_count": 1,
            "failure_count": 0,
            "topic": "araba-dev-updates",
        },
    )
    def test_register_notification_token(
        self,
        mocked_subscribe,
    ):
        token = "f" * 80

        response = self.client.post(
            "/api/notifications/register/",
            {"token": token},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["topic"],
            "araba-dev-updates",
        )
        mocked_subscribe.assert_called_once_with(token)

    def test_register_notification_token_requires_token(self):
        response = self.client.post(
            "/api/notifications/register/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["ok"])
