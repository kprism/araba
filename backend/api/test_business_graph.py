from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import Business, BusinessExperience
from api.services.business_graph_service import (
    add_business_experience,
    persist_businesses,
)
from api.services.research_service import (
    enrich_place_businesses,
    search_real_businesses,
)


class BusinessGraphTests(TestCase):
    def setUp(self):
        self.mission = {
            "category": "치과",
            "location": "창원시 의창구 중동",
            "search_terms": ["치과"],
            "requested_count": 1,
            "search_mode": "category_discovery",
        }
        self.business = {
            "id": "kakao-100",
            "name": "중동좋은치과",
            "description": "치과",
            "category": "의료 > 치과",
            "address": "경남 창원시 의창구 중동 100",
            "road_address": "경남 창원시 의창구 중동로 100",
            "phone": "055-111-2222",
            "latitude": "35.1",
            "longitude": "128.1",
            "place_url": "https://place.map.kakao.com/100",
            "source": "kakao",
            "naver": {
                "matched": True,
                "opening_hours": ["금 09:00-20:30"],
                "parking_available": True,
                "prices": [
                    {
                        "name": "검진",
                        "price": "10,000원",
                    }
                ],
            },
        }

    def test_same_provider_place_is_one_business_object(self):
        persist_businesses(
            [self.business],
            self.mission,
            detail_refreshed=True,
        )
        persist_businesses(
            [
                {
                    **self.business,
                    "phone": "055-999-8888",
                }
            ],
            self.mission,
            detail_refreshed=True,
        )

        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(
            Business.objects.get().phone,
            "055-999-8888",
        )

    @patch("api.services.research_service.httpx.get")
    def test_search_uses_araba_db_before_kakao(self, mocked_get):
        persist_businesses(
            [self.business],
            self.mission,
            detail_refreshed=True,
        )

        result = search_real_businesses(
            self.mission,
            api_key=None,
            quick_cards=True,
        )

        self.assertEqual(result["source"], "araba_db")
        self.assertTrue(result["business_graph_hit"])
        self.assertEqual(
            result["businesses"][0]["name"],
            "중동좋은치과",
        )
        self.assertTrue(
            result["businesses"][0]["araba_cache_hit"]
        )
        mocked_get.assert_not_called()

    @patch(
        "api.services.research_service."
        "enrich_businesses_with_openai_web"
    )
    def test_fresh_cached_details_skip_web_enrichment(
        self,
        mocked_enrich,
    ):
        cached = persist_businesses(
            [self.business],
            self.mission,
            detail_refreshed=True,
        )

        result = enrich_place_businesses(
            cached,
            self.mission,
            openai_api_key="test-key",
            gpt_direct=True,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["naver"]["opening_hours"],
            ["금 09:00-20:30"],
        )
        mocked_enrich.assert_not_called()

    def test_experience_is_stored_separately_and_structured(self):
        stored = persist_businesses(
            [self.business],
            self.mission,
            detail_refreshed=True,
        )[0]

        result = add_business_experience(
            business_id=stored["araba_business_id"],
            raw_text=(
                "주차는 조금 좁아서 불편했고 "
                "대기 15분 정도였지만 설명은 자세하고 친절했어요."
            ),
            verified_visit=False,
        )

        self.assertEqual(BusinessExperience.objects.count(), 1)
        signals = result["structured"]["signals"]
        self.assertEqual(signals["wait_minutes"], 15)
        self.assertEqual(
            signals["parking_experience"],
            "difficult",
        )
        self.assertEqual(signals["explanation"], "positive")
        self.assertEqual(result["experience_count"], 1)


class BusinessExperienceApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        mission = {
            "category": "치과",
            "location": "창원 중동",
        }
        self.business = persist_businesses(
            [
                {
                    "id": "kakao-200",
                    "name": "ARABA치과",
                    "category": "의료 > 치과",
                    "address": "경남 창원시 의창구 중동 200",
                    "source": "kakao",
                }
            ],
            mission,
        )[0]

    def test_create_and_list_experience(self):
        response = self.client.post(
            "/api/research/experiences/create/",
            {
                "business_id": self.business["araba_business_id"],
                "text": "설명을 자세히 해줘서 좋았어요.",
                "verified_visit": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])

        response = self.client.get(
            "/api/research/experiences/",
            {
                "business_id": self.business["araba_business_id"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["experience_count"], 1)
        self.assertEqual(
            response.data["experiences"][0]["text"],
            "설명을 자세히 해줘서 좋았어요.",
        )
