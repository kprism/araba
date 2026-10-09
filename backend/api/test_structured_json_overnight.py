import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from api.services.business_matching_service import match_businesses
from api.services.mission_service import (
    _create_intent_response,
    create_mission,
)
from api.services.live_trainer_service import (
    analyze_and_learn_trainer_feedback,
)


class StructuredIntentOutputTests(TestCase):
    def test_intent_call_uses_strict_json_schema(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=json.dumps(
                {
                    "intent": "conversation",
                    "goal": "테스트",
                    "location": {
                        "value": None,
                        "type": "none",
                        "explicit": False,
                    },
                    "category": None,
                    "subject": None,
                    "search_terms": [],
                    "target_business": None,
                    "count": None,
                    "constraints": [],
                    "criteria": [],
                    "attributes": {},
                    "requested_facts": [],
                    "sort": "none",
                    "needs_fresh_data": False,
                    "needs_clarification": False,
                    "clarification_question": None,
                    "direct_answer": "테스트",
                },
                ensure_ascii=False,
            )
        )

        _create_intent_response(
            client,
            request_text="테스트",
        )

        kwargs = client.responses.create.call_args.kwargs
        fmt = kwargs["text"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertTrue(fmt["strict"])
        self.assertEqual(fmt["name"], "araba_intent")

    @patch("api.services.mission_service.OpenAI")
    def test_followup_sae-byeok_without_hour_bypasses_openai(
        self,
        mocked_openai,
    ):
        request = """[대화 문맥 - 참고용]
{"category":"식당","location":"창원시 의창구 중동","recent_place_results":[{"name":"A식당"},{"name":"B식당"}]}

[현재 요청]
여기서 새벽까지 하는 곳을 알아봐줘"""

        mission = create_mission(
            request,
            api_key="sk-test",
        )

        criterion = next(
            item
            for item in mission["criteria"]
            if item["field"] == "closing_time"
        )
        self.assertEqual(criterion["operator"], "gte")
        self.assertEqual(criterion["value"], "24:00")
        mocked_openai.assert_not_called()

    @patch("api.services.mission_service.OpenAI")
    def test_followup_sae-byeok_two_means_next_day_26(
        self,
        mocked_openai,
    ):
        request = """[대화 문맥 - 참고용]
{"category":"식당","location":"창원시 의창구 중동","recent_place_results":[{"name":"A식당"}]}

[현재 요청]
여기서 새벽 2시까지 하는 곳을 알아봐줘"""

        mission = create_mission(
            request,
            api_key="sk-test",
        )

        criterion = next(
            item
            for item in mission["criteria"]
            if item["field"] == "closing_time"
        )
        self.assertEqual(criterion["value"], "26:00")
        mocked_openai.assert_not_called()


class OvernightBusinessMatchingTests(TestCase):
    def test_after_midnight_closing_is_next_day(self):
        mission = {
            "criteria": [
                {
                    "id": "late",
                    "field": "closing_time",
                    "operator": "gte",
                    "value": "26:00",
                    "required": True,
                    "label": "새벽 2시까지 영업",
                }
            ]
        }
        businesses = [
            {
                "id": "late-shop",
                "name": "새벽식당",
                "naver": {
                    "opening_hours": [
                        "매일 18:00-02:00",
                    ]
                },
            },
            {
                "id": "early-shop",
                "name": "저녁식당",
                "naver": {
                    "opening_hours": [
                        "매일 18:00-23:00",
                    ]
                },
            },
        ]

        result = match_businesses(
            mission,
            businesses,
        )

        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(
            result["matched_businesses"][0]["name"],
            "새벽식당",
        )
        late_row = next(
            row
            for row in result["matrix"]
            if row["business_name"] == "새벽식당"
        )
        self.assertEqual(
            late_row["criteria"][0]["actual"],
            26 * 60,
        )


class StructuredTrainerOutputTests(TestCase):
    @patch("api.services.live_trainer_service.OpenAI")
    def test_trainer_diagnosis_uses_strict_schema(
        self,
        openai_class,
    ):
        payload = {
            "root_cause_type": "matching",
            "root_cause": "자정을 넘긴 폐점시간을 같은 날 02:00으로 비교함",
            "trigger": "영업 종료가 자정을 넘는 업체를 비교할 때",
            "corrective_instruction": "02:00을 다음 날 26:00으로 정규화한다.",
            "can_learn_as_rule": True,
            "needs_code_fix": False,
            "verification": "18:00-02:00 업체가 26:00 조건에 일치한다.",
        }
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=json.dumps(
                payload,
                ensure_ascii=False,
            )
        )
        openai_class.return_value = client

        analyze_and_learn_trainer_feedback(
            api_key="sk-test",
            category="식당",
            request_text="새벽 2시까지 하는 곳 찾아줘",
            assistant_response="찾지 못했어요.",
            trainer_note="02시를 새벽 2시로 기억하지 못했다.",
            actor_role="trainer",
        )

        kwargs = client.responses.create.call_args.kwargs
        fmt = kwargs["text"]["format"]
        self.assertEqual(
            fmt["name"],
            "araba_trainer_diagnosis",
        )
        self.assertTrue(fmt["strict"])
