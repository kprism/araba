from django.test import SimpleTestCase


class ProactiveClarificationTests(SimpleTestCase):
    def _intent(self, **overrides):
        value = {
            "intent": "place_search",
            "goal": "치과를 찾는다.",
            "location": {
                "value": None,
                "type": "none",
                "explicit": False,
            },
            "category": "치과",
            "subject": "치과",
            "search_terms": ["치과"],
            "target_business": None,
            "count": 5,
            "constraints": [],
            "criteria": [],
            "attributes": {},
            "requested_facts": [],
            "sort": "relevance",
            "needs_fresh_data": True,
            "needs_clarification": False,
            "clarification_question": None,
            "direct_answer": None,
        }
        value.update(overrides)
        return value

    def test_place_goal_without_location_asks_required_question(self):
        from api.services.mission_service import (
            _apply_proactive_clarification,
            _attach_task_state,
            _place_mission,
        )

        intent = _apply_proactive_clarification(
            self._intent()
        )
        mission = _attach_task_state(
            _place_mission(intent)
        )

        self.assertTrue(
            intent["needs_clarification"]
        )
        self.assertEqual(
            intent["clarification_question"],
            "어느 지역이나 기준 장소 주변에서 찾을까요?",
        )
        self.assertFalse(
            mission["ready_to_research"]
        )
        self.assertEqual(
            mission["response_mode"],
            "clarify",
        )
        self.assertEqual(
            len(mission["clarification_questions"]),
            1,
        )
        self.assertEqual(
            mission["task_state"]["next_question"],
            "어느 지역이나 기준 장소 주변에서 찾을까요?",
        )

    def test_missing_category_and_location_are_asked_together(self):
        from api.services.mission_service import (
            _apply_proactive_clarification,
            _attach_task_state,
            _place_mission,
        )

        intent = _apply_proactive_clarification(
            self._intent(
                category=None,
                subject=None,
                search_terms=[],
            )
        )
        mission = _attach_task_state(
            _place_mission(intent)
        )

        expected = (
            "찾으려는 업체·장소 종류와 지역 또는 기준 장소를 함께 알려주세요."
        )
        self.assertTrue(
            intent["needs_clarification"]
        )
        self.assertEqual(
            intent["clarification_question"],
            expected,
        )
        self.assertEqual(
            mission["clarification_questions"][0]["question"],
            expected,
        )
        self.assertEqual(
            mission["task_state"]["next_question"],
            expected,
        )

    def test_location_answer_makes_same_goal_research_ready(self):
        from api.services.mission_service import (
            _apply_proactive_clarification,
            _place_mission,
        )

        intent = self._intent(
            location={
                "value": "창원시 의창구 중동",
                "type": "administrative_area",
                "explicit": True,
            },
        )
        intent = _apply_proactive_clarification(intent)
        mission = _place_mission(intent)

        self.assertFalse(
            intent["needs_clarification"]
        )
        self.assertTrue(
            mission["ready_to_research"]
        )
        self.assertEqual(
            mission["location"],
            "창원시 의창구 중동",
        )

    def test_specific_business_does_not_force_location_question(self):
        from api.services.mission_service import (
            _apply_proactive_clarification,
        )

        intent = _apply_proactive_clarification(
            self._intent(
                target_business="서울역",
                category="장소",
                subject="서울역",
                search_terms=["서울역"],
            )
        )

        self.assertFalse(
            intent["needs_clarification"]
        )
