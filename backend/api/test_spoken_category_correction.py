from django.test import SimpleTestCase


class SpokenCategoryCorrectionTests(SimpleTestCase):
    def test_same_utterance_discards_cancelled_food_term(self):
        from api.services.mission_service import (
            _apply_spoken_self_correction,
            _place_mission,
        )

        intent = {
            "intent": "place_search",
            "goal": "창원시 의창구 중동에서 국밥집을 찾는다.",
            "location": {
                "value": "창원시 의창구 중동",
                "type": "administrative_area",
                "explicit": True,
            },
            "category": "식당",
            "subject": "쌈밥 또는 국밥집",
            "search_terms": ["쌈밥", "국밥집"],
            "target_business": None,
            "count": 5,
            "constraints": ["쌈밥집"],
            "criteria": [],
            "attributes": {},
            "requested_facts": [],
            "sort": "relevance",
            "needs_fresh_data": True,
            "needs_clarification": False,
            "clarification_question": None,
            "direct_answer": None,
        }

        request = (
            "[대화 문맥 - 참고용]\n"
            '{"category":"식당","location":"창원시 의창구 중동"}\n\n'
            "[현재 요청]\n"
            "중동에 창원시 의창구 중동에 쌈... 아 "
            "쌈밥이 아니고, 국밥집 좀 알아봐줘"
        )

        corrected = _apply_spoken_self_correction(
            intent,
            request,
        )

        self.assertEqual(
            corrected["category"],
            "식당",
        )
        self.assertEqual(
            corrected["subject"],
            "국밥집",
        )
        self.assertEqual(
            corrected["search_terms"],
            ["국밥"],
        )
        self.assertNotIn(
            "쌈밥",
            " ".join(corrected["constraints"]),
        )

        mission = _place_mission(corrected)
        self.assertEqual(
            mission["location"],
            "창원시 의창구 중동",
        )
        self.assertEqual(
            mission["category"],
            "식당",
        )
        self.assertEqual(
            mission["search_terms"],
            ["국밥"],
        )

    def test_category_correction_replaces_previous_non_food_category(self):
        from api.services.mission_service import (
            _apply_spoken_self_correction,
        )

        intent = {
            "intent": "place_search",
            "category": "치과",
            "subject": "치과",
            "search_terms": ["치과"],
            "constraints": [],
            "target_business": None,
        }

        corrected = _apply_spoken_self_correction(
            intent,
            "치과 말고 피부과 찾아줘",
        )

        self.assertEqual(
            corrected["category"],
            "피부과",
        )
        self.assertEqual(
            corrected["subject"],
            "피부과",
        )
        self.assertEqual(
            corrected["search_terms"],
            ["피부과"],
        )


class ConcreteFoodSearchTests(SimpleTestCase):
    def test_specific_food_query_keeps_provider_ranked_restaurant(self):
        from api.services.research_service import (
            _matches_mission,
        )

        mission = {
            "category": "식당",
            "subject": "국밥집",
            "search_terms": ["국밥"],
            "subcategories": ["식당"],
        }
        document = {
            "place_name": "용지옥",
            "category_name": "음식점 > 한식",
            "category_group_code": "FD6",
        }

        self.assertTrue(
            _matches_mission(
                document,
                mission,
            )
        )

    def test_specific_food_term_is_used_before_broad_restaurant_term(self):
        from api.services.research_service import (
            _search_queries,
        )

        queries = _search_queries(
            {
                "location": "창원시 의창구 중동",
                "category": "식당",
                "subject": "국밥집",
                "search_terms": ["국밥"],
                "subcategories": ["식당"],
                "search_mode": "category_discovery",
            }
        )

        self.assertEqual(
            queries[0],
            "창원시 의창구 중동 국밥",
        )
