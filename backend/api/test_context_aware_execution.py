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
