from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from api.services.google_places_service import enrich_business_with_google_places


class GooglePhotoDiagnosticTests(SimpleTestCase):
    def setUp(self):
        self.business = {
            "id": "K-1",
            "name": "북면식당",
            "address": "경남 창원시 의창구 북면 10",
            "image_url": None,
        }

    def test_unconfigured_key_gives_explicit_reason(self):
        with patch(
            "api.services.google_places_service.get_google_places_key",
            return_value="",
        ):
            result = enrich_business_with_google_places(self.business)
        self.assertEqual(result["google_photo_status"], "not_configured")
        self.assertIsNone(result["image_url"])

    @patch("api.services.google_places_service.httpx.post")
    def test_upstream_403_is_identified_without_key_disclosure(self, post):
        post.return_value = Mock(status_code=403)
        result = enrich_business_with_google_places(
            self.business, api_key="dummy-do-not-leak",
        )
        self.assertEqual(result["google_photo_status"], "provider_http_error")
        self.assertEqual(result["google_search_http_status"], 403)
        self.assertNotIn("dummy-do-not-leak", str(result))

    @patch("api.services.google_places_service.httpx.post")
    def test_verified_identity_without_photos_is_not_shown_as_photo(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {
            "places": [{
                "id": "google-1",
                "displayName": {"text": "북면식당"},
                "formattedAddress": "경남 창원시 의창구 북면 10",
                "photos": [],
            }]
        }
        result = enrich_business_with_google_places(
            self.business, api_key="dummy",
        )
        self.assertEqual(result["google_photo_status"], "no_photo_in_place")
        self.assertIsNone(result["image_url"])

    @patch("api.services.google_places_service.httpx.post")
    def test_unmatched_business_cannot_receive_someone_elses_photo(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {
            "places": [{
                "displayName": {"text": "다른가게"},
                "formattedAddress": "서울시 강남구",
                "photos": [{"name": "places/123/photos/xyz"}],
            }]
        }
        result = enrich_business_with_google_places(
            self.business, api_key="dummy",
        )
        self.assertEqual(result["google_photo_status"], "business_identity_unmatched")
        self.assertIsNone(result["image_url"])
