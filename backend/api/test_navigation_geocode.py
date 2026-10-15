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
    def test_ambiguous_candidates_are_ranked_and_not_auto_navigated(self, fetch):
        fetch.return_value = result(
            point("북면체육관", "경남 창원시 의창구 북면 가상로 2",
                  y="35.250", x="128.630"),
            point("북면고등학교", "경남 창원시 의창구 북면 동전로 36",
                  y="35.270", x="128.650"),
            point("북면병원", "경남 창원시 의창구 북면 가상로 3",
                  y="35.260", x="128.640"),
        )
        data = resolve_navigation_place("북면고", api_key="test")
        # The official high-school entry is the best choice, never silently
        # substitute the unrelated venue or open navigation without evidence.
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["place"]["name"], "북면고등학교")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_similar_name_suggestions_have_closest_first_for_user_choice(self, fetch):
        fetch.return_value = result(
            point("북면문화회관", "경남 창원시 의창구 북면 가상로 2",
                  y="35.250", x="128.630"),
            point("북면병원", "경남 창원시 의창구 북면 가상로 3",
                  y="35.260", x="128.640"),
            point("북면고등학교", "경남 창원시 의창구 북면 동전로 36",
                  y="35.270", x="128.650"),
        )
        data = resolve_navigation_place("북면문화", api_key="test")
        self.assertEqual(data["status"], "ambiguous")
        self.assertEqual(data["candidates"][0]["name"], "북면문화회관")
        # Irrelevant hospitals/schools must not be suggested for a hall.
        self.assertEqual(len(data["candidates"]), 1)

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
        self.assertEqual(data["status"], "not_found")

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
    def test_changwon_bukmyeon_school_variant_search_recovers_exact_identity(self, fetch):
        def search(url, **kwargs):
            term = kwargs["params"]["query"]
            if term == "창원북면고등학교":
                return result(point(
                    "창원북면고등학교", "경남 창원시 의창구 북면 동전로 36",
                ))
            return result()

        fetch.side_effect = search
        data = resolve_navigation_place("창원 북면고등학교", api_key="test")
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["place"]["name"], "창원북면고등학교")
        self.assertEqual(fetch.call_count, 2)

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_colloquial_bukmyeongo_expands_to_formal_high_school(self, fetch):
        def search(url, **kwargs):
            if kwargs["params"]["query"] == "북면고등학교":
                return result(point(
                    "창원북면고등학교", "경남 창원시 의창구 북면 동전로 36",
                ))
            return result()

        fetch.side_effect = search
        data = resolve_navigation_place("북면고", api_key="test")
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["place"]["name"], "창원북면고등학교")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_weak_school_matches_do_not_stop_official_retry(self, fetch):
        def search(url, **kwargs):
            term = kwargs["params"]["query"]
            if term == "창원 북면고등학교":
                return result(
                    point("북면중학교", "경남 창원시 북면 동전로 100"),
                    point("북면초등학교", "경남 창원시 북면 동전로 101"),
                )
            if term == "창원북면고등학교":
                return result(point(
                    "창원북면고등학교", "경남 창원시 의창구 북면 동전로 36",
                ))
            return result()

        fetch.side_effect = search
        data = resolve_navigation_place("창원 북면고등학교", api_key="test")
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["place"]["name"], "창원북면고등학교")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_same_named_schools_in_multiple_cities_require_choice(self, fetch):
        fetch.return_value = result(
            point("창원북면고등학교", "경남 창원시 북면 동전로 36"),
            point("춘천북면고등학교", "강원 춘천시 북면 가상로 11", x="127.50", y="37.90"),
        )
        data = resolve_navigation_place("북면고", api_key="test")
        self.assertEqual(data["status"], "ambiguous")
        self.assertEqual(len(data["candidates"]), 2)

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_other_school_in_changwon_not_substituted(self, fetch):
        fetch.return_value = result(point(
            "북면중학교", "경남 창원시 의창구 북면 동전로 110",
        ))
        data = resolve_navigation_place("창원 북면고등학교", api_key="test")
        self.assertEqual(data["status"], "not_found")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_non_school_fuzzy_city_mismatch_remains_rejected(self, fetch):
        fetch.return_value = result(point(
            "의창파출소", "경남 창원시 의창구 중동",
        ))
        data = resolve_navigation_place("창원시 의창소방서", api_key="test")
        self.assertEqual(data["status"], "not_found")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_spoken_city_is_hard_constraint_and_official_name_retry(self, fetch):
        def search(url, **kwargs):
            term = kwargs["params"]["query"]
            if term == "창원대산고등학교":
                return result(point(
                    "창원대산고등학교", "경남 창원시 의창구 대산면",
                    y="35.330", x="128.690",
                ))
            return result(
                point("경기고등학교", "서울 강남구 영동대로 643",
                      y="37.5", x="127.05"),
                point("경남공업고등학교", "부산 부산진구 전포대로",
                      y="35.2", x="129.06"),
                point("서울고등학교", "서울 서초구",
                      y="37.48", x="127.0"),
            )

        fetch.side_effect = search
        data = resolve_navigation_place("창원 대산 고등학교", api_key="test")
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["place"]["name"], "창원대산고등학교")
        self.assertGreaterEqual(fetch.call_count, 2)

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_explicit_city_rejects_every_wrong_region_candidate(self, fetch):
        fetch.return_value = result(
            point("대산고등학교", "서울 서초구", y="37.5", x="127.0"),
            point("경기고등학교", "서울 강남구", y="37.5", x="127.1"),
            point("경남공업고등학교", "부산 부산진구", y="35.1", x="129.0"),
        )
        data = resolve_navigation_place("경남 창원 대산고등학교", api_key="test")
        self.assertEqual(data["status"], "not_found")
        self.assertEqual(data["candidates"], [])

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_same_city_similar_school_requires_tap_never_opens_wrong_one(self, fetch):
        fetch.return_value = result(
            point("대산고등학교 별관", "경남 창원시 의창구 대산면", y="35.330"),
        )
        data = resolve_navigation_place("창원 대산고등학교", api_key="test")
        self.assertEqual(data["status"], "ambiguous")
        self.assertEqual(data["candidates"][0]["name"], "대산고등학교 별관")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_location_constraint_applies_to_hospitals_and_station_names(self, fetch):
        for query, wrong, correct in [
            ("부산 중앙병원", point("중앙병원", "서울 강남구", y="37.5"),
             point("중앙병원", "부산 동구")),
            ("서울 강남구청", point("강남구청", "경남 창원시"),
             point("강남구청", "서울 강남구 학동로", y="37.51")),
            ("창원 북면약국", point("북면약국", "강원 춘천시 북면", y="37.9"),
             point("북면약국", "경남 창원시 북면")),
        ]:
            with self.subTest(query=query):
                fetch.return_value = result(wrong, correct)
                data = resolve_navigation_place(query, api_key="test")
                self.assertEqual(data["status"], "resolved")
                self.assertEqual(data["place"]["address"], correct["road_address_name"])

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_different_school_type_is_not_suggested(self, fetch):
        fetch.return_value = result(
            point("대산중학교", "경남 창원시 의창구 대산면"),
            point("대산초등학교", "경남 창원시 의창구 대산면", y="35.33"),
        )
        data = resolve_navigation_place("창원 대산고등학교", api_key="test")
        self.assertEqual(data["status"], "not_found")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_location_alias_with_si_suffix_matches_kakao_address(self, fetch):
        fetch.return_value = result(
            point("대산고등학교", "경상남도 창원시 의창구 대산면"),
            point("대산고등학교", "서울 강남구", y="37.5"),
        )
        data = resolve_navigation_place("창원시 대산고등학교", api_key="test")
        self.assertEqual(data["status"], "resolved")
        self.assertIn("창원시", data["place"]["address"])

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_unrelated_similar_named_places_not_offered_without_city(self, fetch):
        fetch.return_value = result(
            point("경기고등학교", "서울 강남구", y="37.5"),
            point("서울고등학교", "서울 서초구", y="37.4"),
        )
        data = resolve_navigation_place("대산고등학교", api_key="test")
        self.assertEqual(data["status"], "not_found")

    @patch("api.services.navigation_geocode_service.httpx.get")
    def test_provider_timeout_is_bounded_and_not_treated_as_coordinates(self, fetch):
        fetch.side_effect = __import__("httpx").ReadTimeout("timeout")
        data = resolve_navigation_place("의창소방서", api_key="test")
        self.assertEqual(data["status"], "provider_error")
        self.assertLessEqual(fetch.call_args.kwargs["timeout"].read, 2.8)
        self.assertLessEqual(fetch.call_args.kwargs["timeout"].connect, 1.0)
