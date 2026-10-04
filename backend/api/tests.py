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
            "configured": False,
            "masked": None,
        },
    )
    def test_openai_status(self, mocked_status):
        response = self.client.get(
            "/api/settings/openai/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            response.data["configured"]
        )

        mocked_status.assert_called_once()


class MissionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("api.views.create_mission", create=True)
    def test_mission_create(self, mocked_create):
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
            "ready_to_research": True,
        }

        with patch(
            "api.services.mission_service.create_mission",
            mocked_create,
        ):
            response = self.client.post(
                "/api/missions/create/",
                {
                    "request": (
                        "오늘 창원에서 BMW X6 타이어 "
                        "교체 가능한 가장 저렴한 곳 알아봐"
                    )
                },
                format="json",
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
