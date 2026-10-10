from unittest.mock import patch

from django.test import TestCase


class RecentSingleBusinessFollowUpTests(TestCase):
    @patch("api.services.mission_service.OpenAI")
    def test_current_order_availability_reuses_single_recent_business(
        self,
        mocked_openai,
    ):
        from api.services.mission_service import create_mission

        request = """[대화 문맥 - 참고용]
{"category":"식당","location":"창원시 의창구 중동","recent_place_results":[{"name":"중동피자","address":"경남 창원시 의창구 중동 1","phone":"055-111-2222"}]}

[현재 요청]
그 한곳에 지금 주문 가능한지 알아봐줘"""

        diagnostics = {}
        mission = create_mission(
            request,
            api_key="sk-test",
            diagnostics=diagnostics,
        )

        self.assertEqual(
            mission["search_mode"],
            "comparison",
        )
        self.assertTrue(
            mission["attributes"]["reuse_recent_results"],
        )
        self.assertTrue(
            mission["attributes"]["reuse_recent_business_only"],
        )
        self.assertEqual(
            mission["requested_count"],
            1,
        )
        self.assertEqual(
            mission["target_business"],
            "중동피자",
        )
        self.assertEqual(
            mission["subject"],
            "중동피자",
        )
        self.assertIn(
            "현재 주문 가능 여부",
            mission["required_facts"],
        )
        availability = next(
            item
            for item in mission["criteria"]
            if item["field"] == "availability"
        )
        self.assertEqual(
            availability["value"],
            True,
        )
        self.assertEqual(
            availability["label"],
            "현재 주문 가능",
        )
        self.assertEqual(
            mission["task_state"]["candidate_scope"],
            "recent_results",
        )
        self.assertEqual(
            diagnostics["route"],
            "recent_place_comparison",
        )
        self.assertEqual(
            diagnostics["openai_elapsed_ms"],
            0,
        )
        mocked_openai.assert_not_called()

    @patch("api.services.mission_service.OpenAI")
    def test_current_delivery_availability_filters_only_recent_results(
        self,
        mocked_openai,
    ):
        from api.services.mission_service import create_mission

        request = """[대화 문맥 - 참고용]
{"category":"식당","location":"창원시 의창구 중동","recent_place_results":[{"name":"A피자"},{"name":"B피자"}]}

[현재 요청]
그중 지금 배달 가능한 곳만 확인해줘"""

        mission = create_mission(
            request,
            api_key="sk-test",
        )

        self.assertEqual(
            mission["search_mode"],
            "comparison",
        )
        self.assertTrue(
            mission["attributes"]["reuse_recent_results"],
        )
        self.assertEqual(
            mission["requested_count"],
            2,
        )
        self.assertIsNone(
            mission["target_business"],
        )
        mocked_openai.assert_not_called()
