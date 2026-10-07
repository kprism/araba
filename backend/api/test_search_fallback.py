from unittest.mock import Mock, patch

from django.test import TestCase


class SearchFallbackTests(TestCase):
    @patch("api.services.research_service.httpx.get")
    def test_coordinate_fallback_recovers_long_location_query(
        self,
        mocked_get,
    ):
        from api.services.research_service import search_real_businesses

        origin = Mock()
        origin.status_code = 200
        origin.json.return_value = {
            "documents": [{
                "x": "128.638",
                "y": "35.258",
                "address": {
                    "address_name": "경남 창원시 의창구 중동",
                },
            }],
        }

        empty = Mock()
        empty.status_code = 200
        empty.json.return_value = {
            "meta": {"total_count": 0},
            "documents": [],
        }

        recovered = Mock()
        recovered.status_code = 200
        recovered.json.return_value = {
            "meta": {"total_count": 1},
            "documents": [{
                "id": "dentist-fallback",
                "place_name": "중동스마트치과",
                "category_name": "의료,건강 > 병원 > 치과",
                "category_group_code": "HP8",
                "address_name": "경남 창원시 의창구 중동 1",
                "road_address_name": "경남 창원시 의창구 중동로 1",
                "x": "128.639",
                "y": "35.259",
                "place_url": "",
            }],
        }

        mocked_get.side_effect = [origin, empty, recovered]

        result = search_real_businesses(
            {
                "search_mode": "category_discovery",
                "location": "경남 창원시 의창구 중동",
                "location_explicit": True,
                "location_context": {
                    "value": "경남 창원시 의창구 중동",
                    "type": "administrative_area",
                },
                "category": "치과",
                "subject": "치과",
                "search_terms": ["치과"],
                "subcategories": ["치과"],
                "requested_count": 1,
            },
            api_key="kakao-test",
            quick_cards=True,
        )

        self.assertEqual(
            result["businesses"][0]["name"],
            "중동스마트치과",
        )
        self.assertEqual(
            mocked_get.call_args_list[1].kwargs["params"]["query"],
            "경남 창원시 의창구 중동 치과",
        )
        self.assertEqual(
            mocked_get.call_args_list[2].kwargs["params"]["query"],
            "치과",
        )
