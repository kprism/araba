import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from api.services.mission_service import (
    _fallback_place_intent_from_request,
    create_mission,
)


class IntentParseFallbackTests(TestCase):
    def test_location_correction_reuses_existing_goal(self):
        request = (
            "[대화 문맥 - 참고용]\n"
            + json.dumps(
                {
                    "category": "식당",
                    "subject": "피자집",
                    "location": "창원시 의창구 도개동",
                    "requested_count": 5,
                },
                ensure_ascii=False,
            )
            + "\n\n[현재 요청]\n"
            + "창원시 의창구 도계동이야"
        )

        fallback = _fallback_place_intent_from_request(
            request
        )

        self.assertIsNotNone(fallback)
        self.assertEqual(
            fallback["location"]["value"],
            "창원시 의창구 도계동",
        )
        self.assertEqual(
            fallback["category"],
            "식당",
        )
        self.assertEqual(
            fallback["subject"],
            "피자집",
        )
        self.assertEqual(
            fallback["search_terms"],
            ["피자"],
        )

    @patch("api.services.mission_service.OpenAI")
    def test_malformed_intent_json_falls_back_for_place_correction(
        self,
        openai_class,
    ):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text="not-json"
        )
        openai_class.return_value = client

        request = (
            "[대화 문맥 - 참고용]\n"
            + json.dumps(
                {
                    "category": "식당",
                    "subject": "피자집",
                    "location": "창원시 의창구 도개동",
                    "requested_count": 5,
                },
                ensure_ascii=False,
            )
            + "\n\n[현재 요청]\n"
            + "창원시 의창구 도계동이야"
        )
        diagnostics = {}

        mission = create_mission(
            request,
            api_key="sk-test",
            diagnostics=diagnostics,
        )

        self.assertEqual(
            mission["location"],
            "창원시 의창구 도계동",
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
            diagnostics["stage"],
            "route_intent",
        )
        self.assertTrue(
            diagnostics["fallback_used"]
        )
        self.assertEqual(
            diagnostics["fallback_stage"],
            "parse_intent",
        )

    @patch("api.services.mission_service.OpenAI")
    def test_malformed_intent_json_does_not_guess_non_place_request(
        self,
        openai_class,
    ):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text="not-json"
        )
        openai_class.return_value = client

        with self.assertRaises(ValueError):
            create_mission(
                "양자역학을 설명해줘",
                api_key="sk-test",
            )

    @patch("api.services.mission_service.OpenAI")
    def test_spoken_clinic_name_correction_skips_slow_model(self, openai_class):
        """Screen failure: a named clinic spelling correction is deterministic."""
        diagnostics = {}
        mission = create_mission(
            "하이스트용치과 하이스트가 아니고 카이스트",
            api_key="sk-test",
            diagnostics=diagnostics,
        )
        self.assertEqual(mission["target_business"], "카이스트용치과")
        self.assertEqual(mission["category"], "치과")
        self.assertEqual(mission["search_mode"], "exact_place")
        self.assertEqual(mission["search_terms"], ["카이스트용치과"])
        self.assertEqual(diagnostics["route"], "named_place_correction")
        self.assertEqual(diagnostics["openai_elapsed_ms"], 0)
        openai_class.assert_not_called()

    @patch("api.services.mission_service.OpenAI")
    def test_short_spoken_correction_reuses_exact_previous_business(self, openai_class):
        contextual = (
            "[대화 문맥 - 참고용]\n" +
            json.dumps({
                "target_business": "하이스트용치과", "category": "치과",
                "location": "창원시 의창구 중동",
            }, ensure_ascii=False)
            + "\n[현재 요청]\n하이스트가 아니고 카이스트"
        )
        mission = create_mission(
            contextual, api_key="sk-test",
        )
        self.assertEqual(mission["target_business"], "카이스트용치과")
        self.assertEqual(mission["location"], "창원시 의창구 중동")
        self.assertEqual(mission["requested_count"], 1)
        openai_class.assert_not_called()

    @patch("api.services.mission_service.OpenAI")
    def test_ambiguous_category_correction_still_routes_through_core(self, openai_class):
        from openai import APITimeoutError
        import httpx
        openai_class.return_value.responses.create.side_effect = APITimeoutError(
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        )
        with self.assertRaises(APITimeoutError):
            create_mission("치과 말고 피부과", api_key="sk-test")
        self.assertEqual(openai_class.return_value.responses.create.call_count, 1)

    @patch("api.services.mission_service.OpenAI")
    def test_core_timeout_recovers_explicitly_located_clinic_search(self, openai_class):
        from openai import APITimeoutError
        import httpx
        openai_class.return_value.responses.create.side_effect = APITimeoutError(
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        )
        diagnostics = {}
        mission = create_mission(
            "창원시 의창구 중동에서 치과 3곳 찾아줘",
            api_key="sk-test", diagnostics=diagnostics,
        )
        self.assertEqual(mission["category"], "치과")
        self.assertEqual(mission["requested_count"], 3)
        self.assertEqual(mission["location"], "창원시 의창구 중동")
        self.assertTrue(diagnostics["fallback_used"])
        self.assertEqual(diagnostics["fallback_stage"], "intent_core_request")
        self.assertEqual(diagnostics["upstream_exception_type"], "APITimeoutError")
        self.assertEqual(openai_class.return_value.responses.create.call_count, 1)

    @patch("api.services.mission_service.OpenAI")
    def test_uncertain_general_question_keeps_original_timeout(self, openai_class):
        from openai import APITimeoutError
        import httpx
        openai_class.return_value.responses.create.side_effect = APITimeoutError(
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        )
        with self.assertRaises(APITimeoutError):
            create_mission("내일 양자역학 강의 계획 짜줘", api_key="sk-test")
