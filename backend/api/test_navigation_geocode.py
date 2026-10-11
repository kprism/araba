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


class NavigationWrongDestinationRegressions(SimpleTestCase):
    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_single_wrong_city_fuzzy_match_is_rejected(self, fetch):
        # Regression: Changwon request accidentally opened a route to Gangwon.
        fetch.return_value = result(point(
            "남전리", "강원 인제군 남면 남전리 4",
            y="38.04", x="128.19",
        ))
        data = resolve_navigation_place("창원시 의창소방서", api_key="test")
        self.assertEqual(data["status"], "not_found")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_same_city_but_unrelated_single_place_is_not_auto_selected(self, fetch):
        fetch.return_value = result(point(
            "의창파출소", "경남 창원시 의창구 중동 771",
        ))
        data = resolve_navigation_place("창원시 의창소방서", api_key="test")
        self.assertEqual(data["status"], "not_found")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_qualified_city_and_exact_venue_name_are_accepted(self, fetch):
        fetch.return_value = result(point(
            "의창소방서", "경상남도 창원시 의창구 의창대로 1",
        ))
        data = resolve_navigation_place("창원시 의창소방서", api_key="test")
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["place"]["name"], "의창소방서")
        self.assertEqual(fetch.call_count, 1)

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_unqualified_unique_exact_name_is_accepted(self, fetch):
        fetch.return_value = result(point(
            "의창소방서", "경남 창원시 의창구",
        ))
        data = resolve_navigation_place("의창소방서", api_key="test")
        self.assertEqual(data["status"], "resolved")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_provider_timeout_is_bounded_and_not_treated_as_coordinates(self, fetch):
        fetch.side_effect = __import__("httpx").ReadTimeout("timeout")
        data = resolve_navigation_place("의창소방서", api_key="test")
        self.assertEqual(data["status"], "provider_error")
        self.assertLessEqual(fetch.call_args.kwargs["timeout"].read, 2.8)
        self.assertLessEqual(fetch.call_args.kwargs["timeout"].connect, 1.0)
