import json
from unittest.mock import patch

from django.test import TestCase

from api.services.business_matching_service import (
    match_businesses,
)
from api.services.mission_service import (
    _fast_recent_place_comparison,
    create_mission,
)


def _contextual_request(current, *, criteria=None):
    context = {
        "category": "타이어점",
        "location": "창원시 의창구 중동",
        "recent_place_results": [
            {
                "rank": index,
                "name": f"타이어업체{index}",
                "address": f"창원시 의창구 중동 {index}",
            }
            for index in range(1, 6)
        ],
    }
    if criteria is not None:
        context["criteria"] = criteria

    return (
        "[대화 문맥 - 참고용]\n"
        + json.dumps(context, ensure_ascii=False)
        + "\n\n[현재 요청]\n"
        + current
    )


class RecentResultFollowupMissionTests(TestCase):
    @patch("api.services.mission_service.OpenAI")
    def test_implicit_saturday_condition_reuses_recent_five(
        self,
        openai_class,
    ):
        mission = create_mission(
            _contextual_request(
                "토요일에도 교체 가능한 곳이 있나"
            ),
            api_key="sk-test",
        )

        self.assertEqual(
            mission["search_mode"],
            "comparison",
        )
        self.assertTrue(
            mission["attributes"][
                "reuse_recent_results"
            ]
        )
        self.assertEqual(
            mission["requested_count"],
            5,
        )
        criterion = next(
            item
            for item in mission["criteria"]
            if item["field"] == "opening_day"
        )
        self.assertEqual(
            criterion["value"],
            "토요일",
        )
        self.assertEqual(
            criterion["label"],
            "토요일 영업",
        )
        openai_class.assert_not_called()

    def test_explicit_other_places_does_not_reuse_recent(self):
        mission = _fast_recent_place_comparison(
            _contextual_request(
                "다른 곳도 토요일 가능한 데 더 찾아줘"
            )
        )
        self.assertIsNone(mission)

    def test_previous_condition_is_kept_when_new_condition_added(self):
        previous = [
            {
                "id": "old-1",
                "field": "parking_available",
                "operator": "eq",
                "value": True,
                "required": True,
                "label": "주차 가능",
            }
        ]

        mission = _fast_recent_place_comparison(
            _contextual_request(
                "토요일에도 되는 곳은?",
                criteria=previous,
            )
        )

        fields = {
            item["field"]
            for item in mission["criteria"]
        }
        self.assertIn(
            "parking_available",
            fields,
        )
        self.assertIn(
            "opening_day",
            fields,
        )


class StrictLocalCohortAndTimeTests(TestCase):
    def test_followup_today_21h_uses_same_three_and_weekday(self):
        from api.services.temporal_service import current_time_context
        context = {
            "category": "치과", "location": "현재 위치",
            "recent_place_results": [
                {"rank": index, "name": f"창원치과{index}",
                 "address": f"경남 창원시 의창구 {index}"}
                for index in range(1, 4)
            ],
        }
        request = (
            "[대화 문맥 - 참고용]\n"
            + json.dumps(context, ensure_ascii=False)
            + "\n[현재 요청]\n"
            + "이중에서 오늘 밤 9시까지 하는 곳 알려줘"
        )
        with patch("api.services.mission_service.OpenAI") as openai:
            mission = create_mission(request, api_key="sk-test")
        openai.assert_not_called()
        self.assertEqual(mission["requested_count"], 3)
        self.assertTrue(mission["attributes"]["reuse_recent_results"])
        criterion = next(
            item for item in mission["criteria"]
            if item["field"] == "closing_time"
        )
        self.assertEqual(criterion["value"], "21:00")
        self.assertEqual(criterion["day"], current_time_context()["weekday"])

    def test_late_hours_on_other_weekday_are_not_evidence_for_today(self):
        from api.services.temporal_service import current_time_context, DAY_NAMES
        today = current_time_context()["weekday"]
        other = DAY_NAMES[(DAY_NAMES.index(today) + 1) % 7]
        result = match_businesses({
            "criteria": [{
                "field": "closing_time", "operator": "gte", "value": "21:00",
                "day": today, "required": True, "label": "오늘 21시 영업",
            }]
        }, [
            {"id": "c1", "name": "오늘21시치과",
             "naver": {"opening_hours": [f"{today} 09:00-21:30"]}},
            {"id": "c2", "name": "내일만21시치과",
             "naver": {"opening_hours": [f"{other} 09:00-22:00",
                                         f"{today} 09:00-18:00"]}},
            {"id": "c3", "name": "시간정보없는치과",
             "naver": {}},
        ])
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["excluded_count"], 1)
        self.assertEqual(result["unverified_count"], 1)
        self.assertEqual(
            [b["name"] for b in result["display_businesses"]],
            ["오늘21시치과"],
        )


class OpeningDayMatchingTests(TestCase):
    def setUp(self):
        self.mission = {
            "criteria": [
                {
                    "id": "sat",
                    "field": "opening_day",
                    "operator": "eq",
                    "value": "토요일",
                    "required": True,
                    "label": "토요일 영업",
                }
            ]
        }

    def test_only_confirmed_saturday_business_is_displayed(self):
        businesses = [
            {
                "id": "1",
                "name": "토요일타이어",
                "naver": {
                    "opening_hours": [
                        "월~금 09:00-18:00",
                        "토요일 09:00-15:00",
                    ]
                },
            },
            {
                "id": "2",
                "name": "토요일휴무",
                "naver": {
                    "opening_hours": [
                        "월~금 09:00-18:00",
                        "토요일 휴무",
                    ]
                },
            },
            {
                "id": "3",
                "name": "요일미확인",
                "naver": {
                    "opening_hours": [
                        "09:00-18:00",
                    ]
                },
            },
        ]

        result = match_businesses(
            self.mission,
            businesses,
        )

        self.assertEqual(
            result["matched_count"],
            1,
        )
        self.assertEqual(
            result["unverified_count"],
            1,
        )
        self.assertEqual(
            result["excluded_count"],
            1,
        )
        self.assertEqual(
            [
                item["name"]
                for item in result[
                    "display_businesses"
                ]
            ],
            ["토요일타이어"],
        )

    def test_every_day_hours_satisfy_saturday(self):
        result = match_businesses(
            self.mission,
            [
                {
                    "id": "1",
                    "name": "매일타이어",
                    "naver": {
                        "opening_hours": [
                            "매일 09:00-20:00",
                        ]
                    },
                }
            ],
        )

        self.assertEqual(
            result["matched_count"],
            1,
        )
