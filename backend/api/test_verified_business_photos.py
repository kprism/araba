from django.test import TestCase

from api.models import Business
from api.services.business_graph_service import (
    serialize_business,
)
from api.services.openai_place_enrichment_service import (
    _image_candidate,
)


class VerifiedBusinessPhotoTests(TestCase):
    def test_first_web_image_without_identity_is_rejected(self):
        business = {
            "name": "워릭프랭클린어학원",
            "category": "영어학원",
            "address": "경남 창원시 의창구 중동중앙로 47",
        }
        raw_results = [
            {
                "type": "image_result",
                "image_url": "https://images.example.com/building.jpg",
                "source_website_url": "https://blog.example.com/post",
                "caption": "창원 중동 건물 전경",
            }
        ]

        result = _image_candidate(
            business,
            raw_results,
            verified_source_urls=[],
            single_business_search=True,
        )

        self.assertIsNone(result)

    def test_image_with_business_and_location_identity_is_kept(self):
        business = {
            "name": "워릭프랭클린어학원",
            "category": "영어학원",
            "address": "경남 창원시 의창구 중동중앙로 47",
        }
        raw_results = [
            {
                "type": "image_result",
                "image_url": "https://images.example.com/warwick.jpg",
                "source_website_url": "https://example.com/warwick",
                "caption": (
                    "워릭프랭클린어학원 창원시 의창구 중동 "
                    "영어학원 내부"
                ),
            }
        ]

        result = _image_candidate(
            business,
            raw_results,
            verified_source_urls=[],
            single_business_search=True,
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["image_url"],
            "https://images.example.com/warwick.jpg",
        )

    def test_cached_unverified_photo_is_not_returned(self):
        record = Business.objects.create(
            provider="kakao",
            provider_place_id="photo-1",
            identity_key="x" * 64,
            name="워릭프랭클린어학원",
            normalized_name="워릭프랭클린어학원",
            category="영어학원",
            address="경남 창원시 의창구 중동중앙로 47",
            snapshot={
                "image_url": "https://wrong.example.com/building.jpg",
                "image_source": "web_evidence",
            },
        )

        data = serialize_business(
            record,
            cache_hit=True,
        )

        self.assertNotIn(
            "image_url",
            data,
        )
        self.assertNotIn(
            "image_source",
            data,
        )

    def test_cached_kakao_place_photo_is_kept(self):
        record = Business.objects.create(
            provider="kakao",
            provider_place_id="photo-2",
            identity_key="y" * 64,
            name="정확한어학원",
            normalized_name="정확한어학원",
            category="영어학원",
            address="경남 창원시 의창구 중동",
            snapshot={
                "image_url": "https://t1.kakaocdn.net/place.jpg",
                "image_source": "kakao_place",
                "image_identity_verified": True,
            },
        )

        data = serialize_business(
            record,
            cache_hit=True,
        )

        self.assertEqual(
            data["image_url"],
            "https://t1.kakaocdn.net/place.jpg",
        )
        self.assertEqual(
            data["image_source"],
            "kakao_place",
        )
