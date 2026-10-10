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
            "parse_intent_fallback",
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
