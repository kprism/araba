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
             "naver": {"matched": True, "page_checked": True, "opening_hours": [f"{today} 09:00-21:30"]}},
            {"id": "c2", "name": "내일만21시치과",
             "naver": {"matched": True, "page_checked": True, "opening_hours": [f"{other} 09:00-22:00",
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


    def test_numeric_count_overrides_mistaken_model_nine_places(self):
        from api.services.mission_service import _enforce_requested_place_count
        source = (
            "[대화 문맥 - 참고용]\n"
            + json.dumps({"location": "창원시"}, ensure_ascii=False)
            + "\n[현재 요청]\n"
            + "내 위치에서 치과 3곳 찾아줘"
        )
        corrected = _enforce_requested_place_count(
            {"intent": "place_search", "requested_count": 9},
            source,
        )
        self.assertEqual(corrected["requested_count"], 3)
        self.assertEqual(
            _enforce_requested_place_count(
                {"intent": "place_search", "requested_count": 5},
                "[현재 요청]\n치과 2군데 알려줘",
            )["requested_count"], 2,
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
                "naver": {"matched": True, "page_checked": True,
                    "opening_hours": [
                        "월~금 09:00-18:00",
                        "토요일 09:00-15:00",
                    ]
                },
            },
            {
                "id": "2",
                "name": "토요일휴무",
                "naver": {"matched": True, "page_checked": True,
                    "opening_hours": [
                        "월~금 09:00-18:00",
                        "토요일 휴무",
                    ]
                },
            },
            {
                "id": "3",
                "name": "요일미확인",
                "naver": {"matched": True, "page_checked": True,
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
                    "naver": {"matched": True, "page_checked": True,
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

class VerifiedWeeklyHoursNormalizationTests(TestCase):
    def setUp(self):
        self.mission = {
            "criteria": [{
                "id": "today21", "field": "closing_time",
                "operator": "gte", "value": "21:00",
                "day": "목요일", "required": True,
            }]
        }

    def test_google_english_ampm_matches_21(self):
        from api.services.temporal_service import structured_business_hours
        value = {
            "name": "창원야간치과", "id": "cw1",
            "google_places": {
                "matched": True,
                "current_opening_hours": [
                    "Thursday: 9:00 AM – 9:30 PM",
                    "Friday: 9:00 AM – 6:00 PM",
                ],
            },
        }
        rows = structured_business_hours(value)
        today = [row for row in rows if row["weekday"] == "목요일"]
        self.assertEqual(today[0]["start_time"], "09:00")
        self.assertEqual(today[0]["end_time"], "21:30")
        matched = match_businesses(self.mission, [value])
        self.assertEqual(matched["matched_count"], 1)

    def test_korean_pm_and_unverified_identity(self):
        normal = {
            "id": "cw2", "name": "밤9시치과",
            "naver": {"matched": True, "page_checked": True,
                      "opening_hours": ["목요일 오전 9:00~오후 9:00"]},
        }
        unverified = {
            "id": "cw3", "name": "검증되지않은치과",
            "google_places": {"matched": False, "current_opening_hours": [
                "Thursday: 9:00 AM - 11:00 PM",
            ]},
        }
        result = match_businesses(self.mission, [normal, unverified])
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["unverified_count"], 1)
        self.assertEqual(result["display_businesses"][0]["name"], "밤9시치과")

    def test_google_provider_periods_are_weekday_start_end(self):
        from api.services.temporal_service import structured_business_hours
        business = {"name": "구글치과", "google_places": {
            "matched": True,
            "current_periods": [{
                "open": {"day": 4, "hour": 9, "minute": 0},
                "close": {"day": 4, "hour": 21, "minute": 30},
            }],
        }}
        rows = structured_business_hours(business)
        self.assertEqual(rows[0]["weekday"], "목요일")
        self.assertEqual(rows[0]["end_minute"], 1290)
        self.assertEqual(match_businesses(
            self.mission, [business],
        )["matched_count"], 1)

    def test_opening_at_2130_does_not_qualify_for_2100(self):
        late = {"id": "cw4", "name": "21시30분개원",
                "naver": {"matched": True, "page_checked": True,
                          "opening_hours": ["목요일 21:30-23:30"]}}
        result = match_businesses(self.mission, [late])
        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["excluded_count"], 1)

    def test_english_weekday_range(self):
        monday = {
            "name": "평일치과",
            "naver": {"matched": True, "page_checked": True,
                      "opening_hours": ["Mo-Fr 09:00-21:00"]},
        }
        self.assertEqual(match_businesses(self.mission, [monday])["matched_count"], 1)

    def test_other_day_does_not_claim_thursday_hours(self):
        wrong = {
            "name": "금요일만야간",
            "naver": {"matched": True, "page_checked": True,
                      "opening_hours": ["금요일 09:00-22:00"]},
        }
        self.assertEqual(match_businesses(self.mission, [wrong])["unverified_count"], 1)

class VerifiedWebHoursFallbackTests(TestCase):
    def setUp(self):
        self.mission = {
            "criteria": [{
                "field": "closing_time", "operator": "gte",
                "value": "21:00", "day": "목요일", "required": True,
            }]
        }

    @staticmethod
    def cafe(name, until, *, verified=True):
        return {
            "id": name, "name": name, "address": "창원시 성산구",
            "naver": {"matched": False, "page_checked": False,
                      "opening_hours": [f"목요일 09:00-{until}"],
                      "opening_hours_source": "openai_web"},
            "openai_web": {
                "matched": verified,
                "identity_confirmed": verified,
                "opening_hours_found": True,
                "opening_hours": [f"목요일 09:00-{until}"],
                "sources": ["https://example.com/evidence"] if verified else [],
            },
        }

    def test_two_of_three_web_sourced_cafes_stay_in_result(self):
        candidates = [
            self.cafe("카페1", "22:00"),
            self.cafe("카페2", "21:30"),
            {"id": "c3", "name": "카페3", "naver": {}},
        ]
        matched = match_businesses(self.mission, candidates)
        self.assertEqual(matched["matched_count"], 2)
        self.assertEqual(matched["unverified_count"], 1)
        self.assertEqual(
            [b["name"] for b in matched["display_businesses"]],
            ["카페1", "카페2"],
        )

    def test_unverified_web_result_remains_unknown(self):
        candidates = [self.cafe("없는근거", "23:00", verified=False)]
        matched = match_businesses(self.mission, candidates)
        self.assertEqual(matched["matched_count"], 0)
        self.assertEqual(matched["unverified_count"], 1)

    def test_monday_provider_does_not_mask_web_verified_thursday(self):
        from api.services.temporal_service import structured_business_hours
        cafe = self.cafe("목요일카페", "22:00")
        cafe["naver"] = {
            "matched": True, "page_checked": True,
            "opening_hours": ["월요일 09:00-18:00"],
        }
        rows = structured_business_hours(cafe)
        self.assertTrue(any(
            r["weekday"] == "목요일" and r.get("end_minute") == 1320
            for r in rows
        ))
        self.assertEqual(
            match_businesses(self.mission, [cafe])["matched_count"], 1,
        )

    @patch("api.services.mission_service.OpenAI")
    def test_korean_spoken_nine_fast_comparison_without_model(self, openai):
        request = _contextual_request(
            "그중 오늘 밤 아홉 시까지 하는 곳 알려줘"
        )
        mission = create_mission(request, api_key="sk-test")
        condition = next(
            c for c in mission["criteria"]
            if c["field"] == "closing_time"
        )
        self.assertEqual(condition["value"], "21:00")
        self.assertEqual(mission["requested_count"], 5)
        openai.assert_not_called()
