from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from api.services.navigation_geocode_service import resolve_navigation_place


def result(*items):
    return Mock(status_code=200, json=lambda: {"documents": list(items)})


def point(name, address, y="35.228", x="128.681"):
    return {
        "place_name": name,
        "address_name": address,
        "road_address_name": address,
        "y": y,
        "x": x,
    }


class NavigationGeocodeTests(SimpleTestCase):
    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_verified_exact_place_coordinates(self, fetch):
        fetch.return_value = result(point(
            "창원시청", "경남 창원시 성산구 중앙대로 151"
        ))
        data = resolve_navigation_place("창원시청", api_key="test")
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["place"]["latitude"], 35.228)
        self.assertEqual(data["place"]["source"], "kakao_local_verified")
        self.assertEqual(
            fetch.call_args.kwargs["headers"]["Authorization"],
            "KakaoAK test",
        )

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_same_name_multiple_locations_requires_clarification(self, fetch):
        fetch.return_value = result(
            point("중앙병원", "창원시 중앙대로 1"),
            point("중앙병원", "서울시 중앙대로 2", y="37.52", x="127.01"),
        )
        data = resolve_navigation_place("중앙병원", api_key="test")
        self.assertEqual(data["status"], "ambiguous")
        self.assertEqual(len(data["candidates"]), 2)

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_no_place_is_not_fabricated(self, fetch):
        fetch.return_value = result()
        data = resolve_navigation_place("존재하지않는도로999", api_key="test")
        self.assertEqual(data["status"], "not_found")
        self.assertEqual(fetch.call_count, 2)

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_unverified_similar_places_do_not_auto_pick_first(self, fetch):
        fetch.return_value = result(
            point("창원문화회관", "경남 창원 문화로 1"),
            point("창원체육관", "경남 창원 문화로 2"),
        )
        data = resolve_navigation_place("창원 시설", api_key="test")
        self.assertEqual(data["status"], "ambiguous")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_invalid_provider_http_status_is_error(self, fetch):
        fetch.return_value = Mock(status_code=401)
        data = resolve_navigation_place("창원시청", api_key="test")
        self.assertEqual(data["status"], "provider_error")

    @patch.dict("os.environ", {"KAKAO_REST_API_KEY": ""})
    def test_missing_provider_key_is_reported(self):
        self.assertEqual(
            resolve_navigation_place("창원시청")["status"],
            "missing_key",
        )

    @patch("api.services.navigation_geocode_service.resolve_navigation_place")
    def test_api_forwards_supplied_key(self, resolver):
        resolver.return_value = {
            "status": "resolved",
            "place": point("창원시청", "창원"),
        }
        response = APIClient().post(
            "/api/navigation/resolve/",
            {"query": "창원시청"},
            format="json",
            HTTP_X_KAKAO_REST_API_KEY="local-my-key",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        resolver.assert_called_once_with("창원시청", api_key="local-my-key")
