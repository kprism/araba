import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import TrainingRule, TrainingRun, TrainingScenario
from api.services.live_trainer_service import (
    analyze_and_learn_trainer_feedback,
    record_correct_feedback,
)


class LiveTrainerServiceTests(TestCase):
    def test_correct_feedback_is_saved_as_positive_example(self):
        result = record_correct_feedback(
            category="치과",
            request_text="중동 치과 5곳 찾아줘",
            assistant_response="치과 5곳을 찾았어요.",
            context={"source": "android_live_trainer"},
        )

        self.assertEqual(
            result["status"],
            "positive_example_saved",
        )
        self.assertEqual(TrainingScenario.objects.count(), 1)
        self.assertEqual(TrainingRun.objects.count(), 1)
        self.assertEqual(
            TrainingRun.objects.get().score,
            100,
        )

    @patch(
        "api.services.live_trainer_service.OpenAI"
    )
    def test_wrong_feedback_learns_immediate_rule(
        self,
        openai_class,
    ):
        payload = {
            "root_cause_type": "context",
            "root_cause": "후속 위치 정정을 이전 위치보다 우선하지 못함",
            "trigger": "사용자가 검색 도중 위치를 정정한 경우",
            "corrective_instruction": (
                "새 위치를 즉시 현재 위치로 교체하고 "
                "기존 목표와 조건을 유지해 다시 검색한다."
            ),
            "can_learn_as_rule": True,
            "needs_code_fix": False,
            "verification": "정정된 위치의 업체만 반환한다.",
        }
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=json.dumps(
                payload,
                ensure_ascii=False,
            )
        )
        openai_class.return_value = client

        result = analyze_and_learn_trainer_feedback(
            api_key="test-key",
            category="치과",
            request_text=(
                "중동 아니고 북면이야. "
                "아까 조건으로 다시 찾아줘"
            ),
            assistant_response="조건에 맞는 업체를 찾지 못했어요.",
            trainer_note="위치 정정을 반영하지 못했다.",
            expected_behavior="북면으로 바꿔 다시 검색해야 한다.",
            context={"source": "android_live_trainer"},
        )

        self.assertEqual(result["status"], "learned")
        self.assertTrue(result["learned"])
        self.assertEqual(TrainingRule.objects.count(), 1)
        rule = TrainingRule.objects.get()
        self.assertEqual(rule.source, "live_trainer")
        self.assertTrue(rule.active)
        self.assertEqual(
            TrainingRun.objects.get().mode,
            "live_trainer",
        )

    @patch(
        "api.services.live_trainer_service.OpenAI"
    )
    def test_code_failure_is_recorded_but_not_activated_as_rule(
        self,
        openai_class,
    ):
        payload = {
            "root_cause_type": "code",
            "root_cause": "후속 질문에서 검색 액션 호출이 누락됨",
            "trigger": "후속 조건 추가 후 재검색이 필요한 경우",
            "corrective_instruction": "검색 액션 호출 경로를 수정한다.",
            "can_learn_as_rule": False,
            "needs_code_fix": True,
            "verification": "후속 질문에서 실제 검색 API가 호출된다.",
        }
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=json.dumps(payload, ensure_ascii=False)
        )
        openai_class.return_value = client

        result = analyze_and_learn_trainer_feedback(
            api_key="test-key",
            category="치과",
            request_text="그중 주차되는 곳만 다시 찾아줘",
            assistant_response="확인해볼게요.",
            trainer_note="말만 하고 검색을 하지 않았다.",
        )

        self.assertEqual(
            result["status"],
            "code_fix_required",
        )
        self.assertFalse(result["learned"])
        self.assertEqual(TrainingRule.objects.count(), 0)
        self.assertEqual(TrainingScenario.objects.count(), 1)
        self.assertEqual(TrainingRun.objects.count(), 1)


class LiveTrainerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_correct_feedback_endpoint(self):
        response = self.client.post(
            "/api/training/live-feedback/",
            {
                "verdict": "correct",
                "category": "식당",
                "request_text": "창원시청 근처 국밥집 찾아줘",
                "assistant_response": "국밥집 5곳을 찾았어요.",
                "context": {
                    "source": "android_live_trainer",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["status"],
            "positive_example_saved",
        )
