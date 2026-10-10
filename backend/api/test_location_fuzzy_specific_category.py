from django.test import TestCase

from api.services.research_service import (
    _fuzzy_admin_document_match,
    _matches_mission,
    _mission_keywords,
)


class SpokenLocationCorrectionTests(TestCase):
    def test_one_syllable_dong_error_recovers_with_parent_scope(self):
        document = {
            "place_name": "도계동 업체",
            "address_name": "경남 창원시 의창구 도계동 100",
            "road_address_name": "경남 창원시 의창구 도계로 1",
        }

        result = _fuzzy_admin_document_match(
            "창원시 의창구 도개동",
            document,
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["leaf"],
            "도계동",
        )
        self.assertIn(
            "창원시",
            result["label"],
        )
        self.assertIn(
            "의창구",
            result["label"],
        )
        self.assertIn(
            "도계동",
            result["label"],
        )

    def test_fuzzy_location_rejects_different_parent_region(self):
        document = {
            "place_name": "다른 지역 업체",
            "address_name": "경남 김해시 내동 100",
            "road_address_name": "경남 김해시 내외중앙로 1",
        }

        result = _fuzzy_admin_document_match(
            "창원시 의창구 도개동",
            document,
        )

        self.assertIsNone(result)


class SpecificCategoryFilteringTests(TestCase):
    def setUp(self):
        self.mission = {
            "search_mode": "category_discovery",
            "category": "식당",
            "subject": "피자집",
            "search_terms": ["피자집"],
            "subcategories": ["식당"],
        }

    def test_pizza_shop_is_kept(self):
        pizza = {
            "place_name": "도계동피자",
            "category_name": "음식점 > 양식 > 피자",
            "category_group_code": "FD6",
        }

        self.assertTrue(
            _matches_mission(
                pizza,
                self.mission,
            )
        )

    def test_pub_is_not_kept_just_because_it_is_food_category(self):
        pub = {
            "place_name": "도계맥주",
            "category_name": "음식점 > 술집 > 맥주,호프",
            "category_group_code": "FD6",
        }

        self.assertFalse(
            _matches_mission(
                pub,
                self.mission,
            )
        )

    def test_spoken_pizza_shop_term_has_pizza_base_variant(self):
        keywords = _mission_keywords(
            self.mission
        )

        self.assertIn("피자", keywords)
