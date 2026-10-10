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
        # Cached lookup must not rediscover businesses through Kakao Local.
        # Fetching a missing official Kakao place photo is allowed.
        self.assertFalse(any(
            "/v2/local/search/" in str(call.args[0])
            for call in mocked_get.call_args_list
        ))

    @patch(
        "api.services.research_service."
        "enrich_businesses_with_openai_web"
    )
    def test_fresh_cached_details_skip_web_enrichment(
        self,
        mocked_enrich,
    ):
        complete = {
            **self.business,
            "image_url": "https://t1.daumcdn.net/verified.jpg",
            "image_source": "kakao_place",
            "image_identity_verified": True,
        }
        cached = persist_businesses(
            [complete], self.mission, detail_refreshed=True,
        )
        result = enrich_place_businesses(
            cached, self.mission,
            openai_api_key="test-key", gpt_direct=True,
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


class BusinessEvidenceRefreshTests(TestCase):
    def setUp(self):
        BusinessGraphTests.setUp(self)

    @patch("api.services.research_service.enrich_businesses_with_naver")
    @patch("api.services.research_service.enrich_businesses_with_kakao_pages")
    @patch("api.services.research_service.enrich_businesses_with_openai_web")
    def test_incomplete_cached_facts_refresh_and_persist(
        self, web, kakao, naver,
    ):
        cached = persist_businesses(
            [{**self.business, "naver": {"matched": False}}],
            self.mission,
            detail_refreshed=True,
        )
        kakao.side_effect = lambda items: items
        naver.side_effect = lambda items, **kwargs: items

        def web_fetch(items, mission, **kwargs):
            return [{
                **item,
                "naver": {
                    "matched": True,
                    "opening_hours": ["월 10:00~18:00"],
                    "parking_available": True,
                    "prices": [{"name": "진료", "price": "10000"}],
                },
                "verified_services": [{
                    "name": "임플란트",
                    "source_url": "https://example.org/clinic",
                }],
                "image_url": "https://t1.daumcdn.net/proven.jpg",
                "image_source": "kakao_place",
                "image_identity_verified": True,
                "image_source_url": "https://place.map.kakao.com/100",
            } for item in items]

        web.side_effect = web_fetch
        updated = enrich_place_businesses(
            cached, self.mission,
            openai_api_key="test-key",
            gpt_direct=True,
        )
        self.assertEqual(updated[0]["image_source"], "kakao_place")
        saved = Business.objects.get()
        self.assertTrue(saved.snapshot["image_identity_verified"])
        self.assertEqual(
            saved.snapshot["naver"]["parking_available"], True
        )
        self.assertEqual(
            saved.snapshot["verified_services"][0]["name"],
            "임플란트",
        )
        web.assert_called_once()

    @patch("api.services.research_service.enrich_businesses_with_naver")
    @patch("api.services.research_service.enrich_businesses_with_kakao_pages")
    @patch("api.services.research_service.enrich_businesses_with_openai_web")
    def test_uncertain_conditions_return_candidates_not_falsely_empty(
        self, web, kakao, naver,
    ):
        cake_mission = {
            "category": "빵집",
            "location": "창원시 의창구 중동",
            "search_terms": ["빵집"],
            "requested_count": 1,
            "search_mode": "category_discovery",
            "criteria": [{
                "field": "service",
                "operator": "contains",
                "value": "케이크",
                "label": "케이크 판매",
                "required": True,
            }],
        }
        business = {
            **self.business, "id": "200",
            "name": "중동빵집", "category": "베이커리",
            "description": "빵집",
            "naver": {},
        }
        persist_businesses(
            [business], cake_mission, detail_refreshed=True,
        )
        kakao.side_effect = lambda items: items
        naver.side_effect = lambda items, **kwargs: items
        web.side_effect = lambda items, mission, **kwargs: items

        result = search_real_businesses(
            cake_mission, api_key="dummy-key",
            openai_api_key="dummy-openai",
            quick_cards=False,
        )
        self.assertEqual(result["businesses"], [])
        self.assertEqual(
            result["unverified_businesses"][0]["name"],
            "중동빵집",
        )
        self.assertEqual(
            result["matching"]["unverified_count"], 1,
        )

    def test_target_specific_price_is_not_another_item_price(self):
        from api.services.business_matching_service import match_businesses
        result = match_businesses(
            {"criteria": [{
                "field": "price",
                "operator": "lte",
                "value": 30000,
                "target": "케이크",
                "required": True,
            }]},
            [{
                "name": "동네빵집",
                "naver": {"prices": [
                    {"name": "단팥빵", "price": "1500원"}
                ]},
            }],
        )
        self.assertEqual(result["unverified_count"], 1)
        self.assertEqual(result["matched_count"], 0)

    def test_service_evidence_fact_stays_in_graph(self):
        stored = persist_businesses([{
            **self.business,
            "verified_services": [{
                "name": "케이크",
                "source_url": "https://example.com/source",
            }],
        }], self.mission, detail_refreshed=True)
        self.assertEqual(
            stored[0]["verified_services"][0]["name"], "케이크",
        )
        fact = Business.objects.get().facts.get(
            key="verified_services"
        )
        self.assertEqual(
            fact.value["value"][0]["source_url"],
            "https://example.com/source",
        )

    def test_transient_photo_identity_flag_does_not_poison_db(self):
        from api.services.business_graph_service import serialize_business
        persist_businesses([{
            **self.business,
            "image_url": "https://google.example/temporary-photo",
            "image_source": "google_places_verified",
            "image_identity_verified": True,
        }], self.mission, detail_refreshed=True)
        stored = serialize_business(Business.objects.get())
        self.assertFalse(stored.get("image_url"))
        self.assertFalse(stored.get("image_identity_verified"))
        self.assertIn("photo", stored["araba_missing_facts"])
