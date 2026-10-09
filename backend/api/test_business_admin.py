from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Business, BusinessExperience, BusinessFact
from api.services.business_admin_service import (
    business_admin_dashboard,
)


class BusinessAdminDashboardTests(TestCase):
    def setUp(self):
        now = timezone.now()

        self.dental = Business.objects.create(
            provider="kakao",
            provider_place_id="dent-1",
            identity_key="a" * 64,
            name="중동미소치과",
            normalized_name="중동미소치과",
            category="의료,건강 > 병원 > 치과",
            address="경남 창원시 의창구 중동",
            road_address="경남 창원시 의창구 중동중앙로 1",
            phone="055-111-1111",
            snapshot={
                "image_url": "https://example.com/dental.jpg",
            },
            last_external_refresh_at=now,
            last_detail_refresh_at=now,
        )
        BusinessFact.objects.create(
            business=self.dental,
            key="opening_hours",
            value={"value": ["월 09:00-20:00"]},
            source="openai_web",
            expires_at=now + timedelta(days=1),
        )
        BusinessFact.objects.create(
            business=self.dental,
            key="parking_available",
            value={"value": True},
            source="openai_web",
            expires_at=now + timedelta(days=1),
        )
        BusinessFact.objects.create(
            business=self.dental,
            key="image_url",
            value={"value": "https://example.com/dental.jpg"},
            source="web",
            expires_at=now + timedelta(days=1),
        )
        BusinessExperience.objects.create(
            business=self.dental,
            raw_text="주차가 편했어요.",
            structured={"tags": ["주차 편리"]},
            rating=5,
            verified_visit=False,
        )

        self.restaurant = Business.objects.create(
            provider="kakao",
            provider_place_id="food-1",
            identity_key="b" * 64,
            name="중동국밥",
            normalized_name="중동국밥",
            category="음식점 > 한식 > 국밥",
            address="경남 창원시 의창구 중동",
            phone="",
            snapshot={},
            last_external_refresh_at=now - timedelta(days=3),
            last_detail_refresh_at=now - timedelta(days=3),
        )
        BusinessFact.objects.create(
            business=self.restaurant,
            key="prices",
            value={"value": [{"name": "국밥", "price": "9000"}]},
            source="openai_web",
            expires_at=now + timedelta(days=1),
        )

        self.inactive = Business.objects.create(
            provider="kakao",
            provider_place_id="old-1",
            identity_key="c" * 64,
            name="폐업후보",
            normalized_name="폐업후보",
            category="음식점 > 카페",
            address="경남 창원시",
            active=False,
        )

    def test_summary_and_leaf_category_counts(self):
        result = business_admin_dashboard({})

        summary = result["summary"]
        self.assertEqual(summary["total_count"], 3)
        self.assertEqual(summary["active_count"], 2)
        self.assertEqual(summary["inactive_count"], 1)

        categories = {
            item["category"]: item["count"]
            for item in summary["category_counts"]
        }
        self.assertEqual(categories["치과"], 1)
        self.assertEqual(categories["국밥"], 1)

        coverage = summary["coverage"]
        self.assertEqual(coverage["phone"], 1)
        self.assertEqual(coverage["hours"], 1)
        self.assertEqual(coverage["parking"], 1)
        self.assertEqual(coverage["prices"], 1)
        self.assertEqual(coverage["image"], 1)
        self.assertEqual(coverage["experience"], 1)

    def test_filters_category_freshness_and_known_data(self):
        result = business_admin_dashboard(
            {
                "category": "치과",
                "freshness": "fresh",
                "has_hours": "true",
                "has_parking": "true",
            }
        )

        self.assertEqual(result["filtered_count"], 1)
        self.assertEqual(
            result["businesses"][0]["name"],
            "중동미소치과",
        )
        self.assertTrue(
            result["businesses"][0]["detail_fresh"]
        )

    def test_search_and_inactive_filter(self):
        search = business_admin_dashboard(
            {"q": "국밥"}
        )
        self.assertEqual(search["filtered_count"], 1)

        inactive = business_admin_dashboard(
            {"active": "inactive"}
        )
        self.assertEqual(inactive["filtered_count"], 1)
        self.assertEqual(
            inactive["businesses"][0]["name"],
            "폐업후보",
        )


class BusinessAdminApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        Business.objects.create(
            provider="kakao",
            provider_place_id="dent-api",
            identity_key="d" * 64,
            name="API치과",
            normalized_name="api치과",
            category="의료 > 치과",
            address="창원시",
        )

    def test_admin_business_dashboard_endpoint(self):
        response = self.client.get(
            "/api/admin/businesses/",
            {
                "category": "치과",
                "page_size": 20,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(response.data["filtered_count"], 1)
        self.assertEqual(
            response.data["businesses"][0]["name"],
            "API치과",
        )
