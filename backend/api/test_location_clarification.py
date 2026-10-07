from unittest.mock import Mock, patch

from django.test import TestCase


class LocationClarificationTests(TestCase):
    @patch("api.services.research_service.httpx.get")
    def test_reference_point_rejects_unrelated_kakao_candidate(
        self,
        mocked_get,
    ):
        from api.services.research_service import (
            _resolve_reference_point_origin,
        )

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "documents": [
                {
                    "place_name": "창원시청",
                    "address_name": "경남 창원시 성산구 중앙동",
                    "road_address_name": "경남 창원시 성산구 중앙대로 151",
                    "x": "128.6819",
                    "y": "35.2279",
                }
            ]
        }
        mocked_get.return_value = response

        result = _resolve_reference_point_origin(
            "이상한시청",
            "kakao-test",
        )

        self.assertIsNone(result)

    @patch("api.services.research_service.httpx.get")
    def test_explicit_unresolved_location_requests_correction(
        self,
        mocked_get,
    ):
        from api.services.research_service import (
            search_real_businesses,
        )

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "documents": [],
        }
        mocked_get.return_value = response

        result = search_real_businesses(
            {
                "category": "치과",
                "subcategories": ["치과"],
                "intent": "place_search",
                "search_mode": "area_discovery",
                "location": "이상한시청",
                "location_explicit": True,
                "location_context": {
                    "value": "이상한시청",
                    "type": "reference_point",
                    "radius_hint_km": 3,
                },
                "subject": "치과",
                "search_terms": ["치과"],
                "requested_count": 5,
            },
            api_key="kakao-test",
            quick_cards=True,
        )

        self.assertTrue(
            result["needs_location_clarification"],
        )
        self.assertEqual(
            result["businesses"],
            [],
        )
        self.assertIn(
            "이상한시청",
            result["clarification_question"],
        )
