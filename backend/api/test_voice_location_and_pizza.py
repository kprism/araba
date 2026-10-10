import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from api.models import Business
from api.services.business_graph_service import (
    cached_businesses_for_mission,
)
from api.services.mission_service import create_mission
from api.services.research_service import (
    _matches_mission,
    _resolve_fuzzy_admin_origin,
)


def _intent_payload(
    *,
    location="창원시 의창구 도개동",
    category="식당",
    subject="피자집",
    search_terms=None,
):
    return {
        "intent": "place_search",
        "goal": "도계동 피자집 찾기",
        "location": {
            "value": location,
            "type": "administrative_area",
            "explicit": True,
        },
        "category": category,
        "subject": subject,
        "search_terms": (
            search_terms
            if search_terms is not None
            else ["식당"]
        ),
        "target_business": None,
        "count": 5,
        "constraints": [],
        "criteria": [],
        "attributes": {},
        "requested_facts": [],
        "sort": "relevance",
        "needs_fresh_data": True,
        "needs_clarification": False,
        "clarification_question": None,
        "direct_answer": None,
    }


class IntentRecoveryTests(TestCase):
    @patch("api.services.mission_service.OpenAI")
    def test_pizza_request_recovers_specific_search_term(
        self,
        openai_class,
    ):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=json.dumps(
                _intent_payload(),
                ensure_ascii=False,
            )
        )
        openai_class.return_value = client

        mission = create_mission(
            "창원시 의창구 도개동에서 피자집 알려줘",
            api_key="sk-test",
        )

        self.assertEqual(
            mission["category"],
            "식당",
        )
        self.assertEqual(
            mission["search_terms"],
            ["피자"],
        )
        self.assertEqual(
            mission["subject"],
            "피자집",
        )


class VoiceLocationRecoveryTests(TestCase):
    @patch("api.services.research_service.httpx.get")
    def test_dogae_voice_error_recovers_dogye_from_parent_scoped_results(
        self,
        mocked_get,
    ):
        empty = Mock()
        empty.status_code = 200
        empty.json.return_value = {
            "documents": [],
        }

        pizza_result = Mock()
        pizza_result.status_code = 200
        pizza_result.json.return_value = {
            "documents": [
                {
                    "place_name": "도계피자",
                    "category_name": "음식점 > 양식 > 피자",
                    "category_group_code": "FD6",
                    "address_name": "경남 창원시 의창구 도계동 1",
                    "road_address_name": "경남 창원시 의창구 도계로 1",
                    "x": "128.640",
                    "y": "35.260",
                }
            ]
        }

        mocked_get.side_effect = [
            empty,
            pizza_result,
        ]

        result = _resolve_fuzzy_admin_origin(
            "창원시 의창구 도개동",
            "kakao-test",
            mission={
                "category": "식당",
                "subject": "피자집",
                "search_terms": ["피자"],
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["corrected_leaf"],
            "도계동",
        )
        self.assertEqual(
            result["spoken_location"],
            "창원시 의창구 도개동",
        )
        self.assertEqual(
            mocked_get.call_args_list[1].kwargs[
                "params"
            ]["query"],
            "창원시 의창구 피자",
        )


class PizzaRelevanceTests(TestCase):
    def setUp(self):
        self.mission = {
            "search_mode": "category_discovery",
            "location": "창원시 의창구 도계동",
            "category": "식당",
            "subject": "피자집",
            "search_terms": ["피자"],
            "subcategories": ["식당"],
            "requested_count": 5,
        }

    def test_pub_is_rejected_even_if_name_contains_pizza(self):
        document = {
            "place_name": "피자앤비어",
            "category_name": "음식점 > 술집 > 맥주,호프",
            "category_group_code": "FD6",
        }

        self.assertFalse(
            _matches_mission(
                document,
                self.mission,
            )
        )

    def test_actual_pizza_category_is_kept(self):
        document = {
            "place_name": "도계피자",
            "category_name": "음식점 > 양식 > 피자",
            "category_group_code": "FD6",
        }

        self.assertTrue(
            _matches_mission(
                document,
                self.mission,
            )
        )

    def test_cached_business_graph_does_not_return_pub_for_pizza(self):
        Business.objects.create(
            provider="kakao",
            provider_place_id="pizza-1",
            identity_key="p" * 64,
            name="도계피자",
            normalized_name="도계피자",
            category="음식점 > 양식 > 피자",
            address="경남 창원시 의창구 도계동 1",
            road_address="경남 창원시 의창구 도계로 1",
        )
        Business.objects.create(
            provider="kakao",
            provider_place_id="pub-1",
            identity_key="u" * 64,
            name="피자앤비어",
            normalized_name="피자앤비어",
            category="음식점 > 술집 > 맥주,호프",
            address="경남 창원시 의창구 도계동 2",
            road_address="경남 창원시 의창구 도계로 2",
        )

        result = cached_businesses_for_mission(
            {
                **self.mission,
                "requested_count": 1,
            },
            requested_count=1,
        )

        self.assertTrue(result["complete"])
        self.assertEqual(
            [item["name"] for item in result["businesses"]],
            ["도계피자"],
        )
