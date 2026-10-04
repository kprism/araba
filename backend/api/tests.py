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
