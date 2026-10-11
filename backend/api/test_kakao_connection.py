from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase
from rest_framework.test import APIClient


class KakaoConnectionDiagnosticsTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/settings/kakao/test/"

    def _call(self, key="test-rest-key"):
        return self.client.post(
            self.url,
            HTTP_X_KAKAO_REST_API_KEY=key,
        )

    @patch("httpx.get")
    def test_successful_search_reports_no_photo_field(self, get):
        get.return_value = Mock(status_code=200)
        get.return_value.json.return_value = {
            "documents": [{"id": "1", "place_name": "창원시청"}],
        }
        result = self._call()
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.data["connected"])
        self.assertFalse(result.data["photos_available_in_local_api"])
        self.assertEqual(result.data["result_count"], 1)
        self.assertNotIn("test-rest-key", str(result.data))
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "KakaoAK test-rest-key")

    @patch("httpx.get")
    def test_no_key_does_not_call_upstream(self, get):
        result = self._call(key="")
        self.assertEqual(result.status_code, 400)
        self.assertFalse(result.data["connected"])
        get.assert_not_called()

    @patch("httpx.get")
    def test_unauthorized_key(self, get):
        get.return_value = Mock(status_code=401)
        get.return_value.json.return_value = {"code": -401}
        result = self._call()
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.data["provider_status"], 401)
        self.assertIn("인증 실패", result.data["message"])

    @patch("httpx.get")
    def test_forbidden_permission(self, get):
        get.return_value = Mock(status_code=403)
        get.return_value.json.return_value = {"code": -3}
        result = self._call()
        self.assertEqual(result.status_code, 400)
        self.assertIn("권한", result.data["message"])

    @patch("httpx.get")
    def test_quota_exceeded(self, get):
        get.return_value = Mock(status_code=429)
        get.return_value.json.return_value = {"code": -10}
        result = self._call()
        self.assertEqual(result.status_code, 400)
        self.assertIn("한도", result.data["message"])

    @patch("httpx.get", side_effect=httpx.ConnectTimeout("timeout"))
    def test_upstream_timeout(self, get):
        result = self._call()
        self.assertEqual(result.status_code, 502)
        self.assertFalse(result.data["connected"])
