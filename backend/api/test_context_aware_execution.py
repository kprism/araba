from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from api.models import Business

from api.services.business_matching_service import (
    match_businesses,
)
from api.services.business_graph_service import (
    cached_businesses_for_mission,
)
from api.services.execution_planner_service import (
    build_execution_plan,
)
from api.services.google_places_service import (
    enrich_business_with_google_places,
)
from api.services.image_identity_service import (
    enforce_business_image_identity,
)
from api.services.mission_service import (
    _apply_device_context_to_mission,
    _apply_device_location_to_intent,
)
from api.services.temporal_service import (
    evaluate_business_now,
)


KST = ZoneInfo("Asia/Seoul")


class TemporalAvailabilityTests(TestCase):
    def test_open_now_inside_confirmed_kst_hours(self):
        business = {
            "name": "피자가게",
            "naver": {
                "opening_hours": [
                    "매일 09:00-22:00",
                ]
            },
        }
        now = datetime(
            2026,
            10,
            10,
            21,
            30,
            tzinfo=KST,
        )

        result = evaluate_business_now(
            business,
            now=now,
        )

        self.assertTrue(result["is_open_now"])
        self.assertTrue(result["orderable_now"])
        self.assertEqual(
            result["timezone"],
            "Asia/Seoul",
        )

    def test_closed_now_outside_confirmed_hours(self):
        business = {
            "name": "피자가게",
            "naver": {
                "opening_hours": [
                    "매일 09:00-22:00",
                ]
            },
        }
        now = datetime(
            2026,
            10,
            10,
            23,
            10,
            tzinfo=KST,
        )

        result = evaluate_business_now(
            business,
            now=now,
        )

        self.assertFalse(result["is_open_now"])
        self.assertFalse(result["orderable_now"])

    def test_previous_day_overnight_range_is_open_after_midnight(self):
        business = {
            "name": "새벽피자",
            "naver": {
                "opening_hours": [
                    "금요일 18:00-02:00",
                ]
            },
        }
        saturday_1am = datetime(
            2026,
            10,
            10,
            1,
            0,
            tzinfo=KST,
        )

        result = evaluate_business_now(
            business,
            now=saturday_1am,
        )

        self.assertTrue(result["is_open_now"])

    @patch(
        "api.services.business_matching_service.evaluate_business_now"
    )
    def test_current_order_criterion_uses_temporal_engine(
        self,
        evaluate_now,
    ):
        evaluate_now.return_value = {
            "orderable_now": True,
        }
        mission = {
            "criteria": [
                {
                    "id": "order-now",
                    "field": "availability",
                    "operator": "eq",
                    "value": True,
                    "required": True,
                    "label": "현재 주문 가능",
                }
            ]
        }

        result = match_businesses(
            mission,
            [{"name": "중동피자"}],
        )

        self.assertEqual(
            result["matched_count"],
            1,
        )
        self.assertEqual(
            result["matrix"][0]["criteria"][0]["source"],
            "business_hours_kst",
        )


class DeviceLocationMissionTests(TestCase):
    def setUp(self):
        self.intent = {
            "intent": "place_search",
            "goal": "내 주변 피자집 찾기",
            "location": {
                "value": None,
                "type": "none",
                "explicit": False,
            },
            "category": "식당",
            "subject": "피자집",
            "search_terms": ["피자"],
            "target_business": None,
            "count": 5,
            "constraints": [],
            "criteria": [],
            "attributes": {},
            "requested_facts": [],
            "sort": "distance",
            "needs_fresh_data": True,
            "needs_clarification": False,
            "clarification_question": None,
            "direct_answer": None,
        }
        self.device = {
            "latitude": 35.23,
            "longitude": 128.68,
            "accuracy_m": 12.0,
            "captured_at": "2026-10-10T12:00:00Z",
        }

    def test_current_location_language_binds_device_context(self):
        intent = _apply_device_location_to_intent(
            self.intent,
            "내 주변 피자집 찾아줘",
            self.device,
        )

        self.assertTrue(
            intent["attributes"][
                "use_device_location"
            ]
        )
        self.assertEqual(
            intent["location"]["value"],
            "현재 위치",
        )

        mission = {
            "intent": "place_search",
            "response_mode": "clarify",
            "ready_to_research": False,
            "location": None,
            "location_explicit": False,
            "location_context": {
                "value": None,
                "type": "none",
            },
            "missing_information": ["지역"],
            "clarification_questions": [
                {"question": "어디에서 찾을까요?"}
            ],
            "known_facts": {},
        }
        mission = _apply_device_context_to_mission(
            mission,
            "내 주변 피자집 찾아줘",
            self.device,
        )

        self.assertEqual(
            mission["location_context"]["type"],
            "device_location",
        )
        self.assertEqual(
            mission["location_context"]["latitude"],
            35.23,
        )
        self.assertTrue(
            mission["ready_to_research"]
        )
        self.assertEqual(
            mission["clarification_questions"],
            [],
        )

    def test_missing_permission_becomes_location_clarification(self):
        intent = _apply_device_location_to_intent(
            self.intent,
            "지금 내가 있는 곳 근처 피자집 찾아줘",
            None,
        )

        self.assertTrue(
            intent["needs_clarification"]
        )
        self.assertIn(
            "위치 권한",
            intent["clarification_question"],
        )


class ExecutionPlannerTests(TestCase):
    def test_plan_derives_search_identity_time_match_and_agent_tasks(self):
        mission = {
            "intent": "place_search",
            "search_mode": "comparison",
            "summary": "그 한 곳 지금 주문 가능해?",
            "user_goal": "그 한 곳 지금 주문 가능해?",
            "attributes": {
                "reuse_recent_results": True,
            },
            "location_context": {
                "type": "device_location",
            },
            "needs_fresh_data": True,
            "criteria": [
                {
                    "field": "availability",
                    "label": "현재 주문 가능",
                }
            ],
        }

        plan = build_execution_plan(mission)
        ids = {
            item["id"]
            for item in plan["tasks"]
        }

        self.assertIn(
            "resolve_device_location",
            ids,
        )
        self.assertIn(
            "load_recent_candidates",
            ids,
        )
        self.assertIn(
            "verify_business_identity",
            ids,
        )
        self.assertIn(
            "evaluate_current_kst",
            ids,
        )
        self.assertIn(
            "query_business_agent",
            ids,
        )
        self.assertIn(
            "compare_all_conditions",
            ids,
        )
        self.assertNotIn(
            "discover_missing_candidates",
            ids,
        )


class ImageIdentityGuardTests(TestCase):
    def test_unverified_web_photo_is_hidden(self):
        item = enforce_business_image_identity(
            {
                "name": "학원",
                "image_url": "https://example.com/wrong.jpg",
                "image_source": "openai_web",
            }
        )

        self.assertIsNone(
            item["image_url"]
        )
        self.assertFalse(
            item["image_identity_verified"]
        )
        self.assertEqual(
            item["unverified_image_url"],
            "https://example.com/wrong.jpg",
        )

    def test_verified_google_photo_is_kept(self):
        item = enforce_business_image_identity(
            {
                "name": "학원",
                "image_url": "https://example.com/right.jpg",
                "image_source": "google_places_verified",
                "image_identity_verified": True,
            }
        )

        self.assertEqual(
            item["image_url"],
            "https://example.com/right.jpg",
        )


class GooglePlacesAdapterTests(TestCase):
    @patch(
        "api.services.google_places_service.httpx.get"
    )
    @patch(
        "api.services.google_places_service.httpx.post"
    )
    def test_verified_place_supplies_photo_and_open_now(
        self,
        post,
        get,
    ):
        post_response = Mock()
        post_response.status_code = 200
        post_response.json.return_value = {
            "places": [
                {
                    "id": "place-1",
                    "displayName": {
                        "text": "중동피자",
                    },
                    "formattedAddress": (
                        "대한민국 경상남도 창원시 "
                        "의창구 중동중앙로 10"
                    ),
                    "currentOpeningHours": {
                        "openNow": True,
                        "weekdayDescriptions": [
                            "토요일: 11:00-23:00",
                        ],
                    },
                    "photos": [
                        {
                            "name": (
                                "places/place-1/photos/photo-1"
                            )
                        }
                    ],
                    "delivery": True,
                    "takeout": True,
                    "reservable": False,
                }
            ]
        }
        post.return_value = post_response

        photo_response = Mock()
        photo_response.status_code = 200
        photo_response.json.return_value = {
            "photoUri": "https://example.com/place-photo.jpg",
        }
        get.return_value = photo_response

        result = enrich_business_with_google_places(
            {
                "name": "중동피자",
                "address": "경남 창원시 의창구 중동중앙로 10",
                "road_address": "경남 창원시 의창구 중동중앙로 10",
            },
            api_key="google-test",
        )

        self.assertEqual(
            result["image_source"],
            "google_places_verified",
        )
        self.assertTrue(
            result["image_identity_verified"]
        )
        self.assertTrue(
            result["google_places"]["open_now"]
        )
        self.assertTrue(
            result["google_places"]["delivery"]
        )

    @patch(
        "api.services.google_places_service.httpx.post"
    )
    def test_wrong_business_name_never_overrides_photo(
        self,
        post,
    ):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "places": [
                {
                    "id": "wrong",
                    "displayName": {
                        "text": "완전히다른학원",
                    },
                    "formattedAddress": "경남 창원시 의창구 중동",
                    "photos": [
                        {"name": "places/wrong/photos/1"}
                    ],
                }
            ]
        }
        post.return_value = response

        result = enrich_business_with_google_places(
            {
                "name": "워릭프랭클린어학원",
                "address": "경남 창원시 의창구 중동중앙로 47",
            },
            api_key="google-test",
        )

        self.assertNotIn(
            "google_places",
            result,
        )
        self.assertFalse(
            bool(result.get("image_url")),
        )


class NearbyBusinessGraphTests(TestCase):
    def test_device_location_uses_coordinates_not_literal_current_location(self):
        Business.objects.create(
            provider="kakao",
            provider_place_id="near-pizza",
            identity_key="n" * 64,
            name="근처피자",
            normalized_name="근처피자",
            category="음식점 > 피자",
            address="경남 창원시 의창구 중동",
            latitude="35.2301",
            longitude="128.6801",
        )
        Business.objects.create(
            provider="kakao",
            provider_place_id="far-pizza",
            identity_key="f" * 64,
            name="먼피자",
            normalized_name="먼피자",
            category="음식점 > 피자",
            address="부산광역시",
            latitude="35.1000",
            longitude="129.0400",
        )

        result = cached_businesses_for_mission(
            {
                "intent": "place_search",
                "location": "현재 위치",
                "location_context": {
                    "type": "device_location",
                    "latitude": 35.23,
                    "longitude": 128.68,
                    "radius_hint_km": 3,
                },
                "category": "식당",
                "subject": "피자집",
                "search_terms": ["피자"],
            },
            requested_count=1,
        )

        self.assertTrue(result["complete"])
        self.assertEqual(
            result["businesses"][0]["name"],
            "근처피자",
        )
        self.assertEqual(
            result["businesses"][0]["distance_source"],
            "device_location",
        )


class RegressionFamiliesTests(TestCase):
    """Cross-category and cross-location failures must not return as variants."""

    def test_split_three_independent_place_tasks(self):
        from api.services.mission_service import split_independent_requests

        request = (
            "창원시 중동 치과 3곳 찾아주고, "
            "창원시청 주변 식당 3곳도 찾아줘. "
            "그리고 도계동 피자집 몇 곳인지 조사해줘"
        )
        tasks = split_independent_requests(request)
        self.assertEqual(len(tasks), 3)
        self.assertIn("치과", tasks[0])
        self.assertIn("식당", tasks[1])
        self.assertIn("피자집", tasks[2])

    def test_conditions_are_not_split_into_new_tasks(self):
        from api.services.mission_service import split_independent_requests

        request = (
            "창원시 중동 치과 5곳 찾아줘. "
            "그리고 주차되고 토요일 진료하는 곳으로"
        )
        self.assertEqual(
            split_independent_requests(request),
            [request],
        )

    def test_hard_conditions_survive_incomplete_intent(self):
        from api.services.mission_service import (
            _enforce_explicit_evidence_conditions,
        )

        intent = {
            "intent": "place_search",
            "category": "치과",
            "subject": "치과",
            "criteria": [],
        }
        repaired = _enforce_explicit_evidence_conditions(
            intent,
            "창원 중동 주차 가능하고 토요일 진료하는 임플란트 치과 찾아줘",
        )
        fields = {
            item["field"]: item["value"]
            for item in repaired["criteria"]
        }
        self.assertEqual(fields["opening_day"], "토요일")
        self.assertTrue(fields["parking_available"])
        self.assertEqual(fields["service"], "임플란트")

    def test_unverified_cake_sale_never_becomes_verified(self):
        from api.services.business_matching_service import match_businesses
        from api.services.mission_service import (
            _enforce_explicit_evidence_conditions,
        )

        mission = _enforce_explicit_evidence_conditions(
            {
                "intent": "place_search",
                "category": "빵집",
                "subject": "빵집",
                "criteria": [],
            },
            "아까 찾은 빵집에서 케이크 파는 곳을 알려줘",
        )
        matching = match_businesses(
            mission,
            [
                {
                    "name": "동네빵집",
                    "category": "베이커리",
                    "address": "창원시 중동",
                }
            ],
        )
        self.assertFalse(matching["answer_ready"])
        self.assertEqual(matching["unverified_count"], 1)
        self.assertEqual(matching["display_businesses"], [])

    def test_saturday_cannot_be_confirmed_from_weekday_hours_only(self):
        from api.services.business_matching_service import match_businesses

        matching = match_businesses(
            {
                "criteria": [{
                    "field": "opening_day",
                    "operator": "eq",
                    "value": "토요일",
                    "required": True,
                    "label": "토요일 진료",
                }],
            },
            [{
                "name": "토요일 미확인 치과",
                "naver": {
                    "opening_hours": ["월요일 09:30~18:30", "화요일 09:30~19:00"],
                },
            }],
        )
        self.assertFalse(matching["answer_ready"])
        self.assertEqual(matching["matched_count"], 0)
        self.assertEqual(matching["unverified_count"], 1)

    def test_identity_matched_google_saturday_hours_count(self):
        from api.services.business_matching_service import match_businesses

        matching = match_businesses(
            {
                "criteria": [{
                    "field": "opening_day",
                    "operator": "eq",
                    "value": "토요일",
                    "required": True,
                    "label": "토요일 진료",
                }],
            },
            [{
                "name": "토요일 영업 치과",
                "google_places": {
                    "matched": True,
                    "regular_opening_hours": ["토요일: 09:00-13:00"],
                },
            }],
        )
        self.assertEqual(matching["matched_count"], 1)

    def test_device_radius_rejects_other_city_and_missing_coordinates(self):
        from api.services.research_service import _inside_verified_radius

        origin = {
            "source": "device_location",
            "latitude": 35.23,
            "longitude": 128.68,
        }
        self.assertTrue(_inside_verified_radius(
            {"y": "35.231", "x": "128.681"},
            origin,
            3,
        ))
        self.assertFalse(_inside_verified_radius(
            {"y": "35.1796", "x": "129.0756"},
            origin,
            3,
        ))
        self.assertFalse(_inside_verified_radius(
            {"place_name": "주소 없는 업체"},
            origin,
            3,
        ))


    def test_last_spoken_location_correction_overrides_bad_recognition(self):
        from api.services.mission_service import (
            _apply_latest_spoken_location_correction,
        )

        intent = {
            "intent": "place_search",
            "location": {
                "value": "성원시 의청구 중동",
                "type": "administrative_area",
                "explicit": True,
            },
            "attributes": {"reuse_recent_results": True},
            "target_business": "지난 가게",
        }
        corrected = _apply_latest_spoken_location_correction(
            intent,
            "성원시 의청구 중동에 치과 찾아줘. "
            "잠깐 성원시가 아니고 창원시 의창구 중동이야",
        )
        self.assertEqual(
            corrected["location"]["value"],
            "창원시 의창구 중동",
        )
        self.assertTrue(corrected["location"]["explicit"])
        self.assertNotIn("reuse_recent_results", corrected["attributes"])

    @patch("api.services.kakao_place_service.inspect_kakao_place_page")
    def test_kakao_photo_requires_exact_id(self, inspect):
        from api.services.kakao_place_service import _enrich_one_business

        inspect.return_value = {
            "checked": True,
            "image_url": "https://t1.daumcdn.net/real.jpg",
            "source_url": "https://place.map.kakao.com/12345",
        }
        result = _enrich_one_business({
            "id": "12345",
            "name": "정확한 치과",
            "place_url": "https://place.map.kakao.com/12345",
        })
        self.assertTrue(result["image_identity_verified"])
        self.assertEqual(
            result["image_source_url"],
            "https://place.map.kakao.com/12345",
        )

        inspect.return_value["source_url"] = (
            "https://place.map.kakao.com/99999"
        )
        mismatch = _enrich_one_business({
            "id": "12345",
            "name": "다른 치과",
            "place_url": "https://place.map.kakao.com/12345",
        })
        self.assertFalse(bool(mismatch.get("image_url")))
        self.assertEqual(
            mismatch["kakao_photo_status"],
            "identity_not_confirmed",
        )
