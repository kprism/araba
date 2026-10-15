from django.test import SimpleTestCase

from api.services.business_matching_service import match_businesses
from api.services.temporal_service import _hours_lines


class VerifiedHoursIdentityTests(SimpleTestCase):
    def setUp(self):
        self.base = {
            "id": "kakao-101",
            "name": "창원치과A",
            "address": "경남 창원시 의창구",
        }
        self.mission = {
            "criteria": [{
                "id": "today21",
                "field": "closing_time",
                "operator": "gte",
                "value": "21:00",
                "day": "목요일",
                "required": True,
                "label": "오늘 21시 진료",
            }],
        }

    def test_unmatched_naver_page_cannot_confirm_even_if_23h(self):
        item = {**self.base, "naver": {
            "matched": False,
            "page_checked": True,
            "opening_hours": ["목요일 09:00-23:00"],
        }}
        matching = match_businesses(self.mission, [item])
        self.assertEqual(matching["matched_count"], 0)
        self.assertEqual(matching["unverified_count"], 1)
        self.assertEqual(matching["display_businesses"], [])

    def test_uninspected_naver_page_cannot_confirm(self):
        item = {**self.base, "naver": {
            "matched": True,
            "page_checked": False,
            "opening_hours": ["목요일 09:00-23:00"],
        }}
        matching = match_businesses(self.mission, [item])
        self.assertEqual(matching["matched_count"], 0)

    def test_matched_provider_specific_hours_may_confirm(self):
        item = {**self.base, "naver": {
            "matched": True,
            "page_checked": True,
            "opening_hours": ["목요일 09:00-21:30"],
        }}
        matching = match_businesses(self.mission, [item])
        self.assertEqual(matching["matched_count"], 1)
        self.assertEqual(matching["display_businesses"][0]["id"], "kakao-101")

    def test_wrong_weekday_and_missing_hours_never_confirm(self):
        item = {**self.base, "naver": {
            "matched": True,
            "page_checked": True,
            "opening_hours": ["금요일 09:00-23:00", "목요일 09:00-18:00"],
        }}
        unknown = {**self.base, "id": "kakao-102", "name": "창원치과B"}
        result = match_businesses(self.mission, [item, unknown])
        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["unverified_count"], 1)
        self.assertEqual(result["excluded_count"], 1)

    def test_unmatched_google_current_hours_cannot_confirm(self):
        item = {**self.base, "google_places": {
            "matched": False,
            "current_opening_hours": ["목요일 09:00-23:00"],
        }}
        self.assertEqual(match_businesses(self.mission, [item])["matched_count"], 0)
        self.assertEqual(_hours_lines(item)[0], [])
