from unittest.mock import patch

from django.test import TestCase

from api.services.research_service import enrich_place_businesses


class KakaoHttpPhotoRegressionTests(TestCase):
    @patch("api.services.research_service.enrich_businesses_with_openai_web")
    @patch("api.services.research_service.enrich_businesses_with_kakao_pages")
    def test_documented_http_place_url_is_inspected_for_photo(self, kakao_pages, web):
        def provide_photo(businesses):
            return [
                {
                    **item,
                    "image_url": "https://t1.kakaocdn.net/place.jpg",
                    "image_source": "kakao_place",
                    "image_identity_verified": True,
                    "kakao_photo_status": "found",
                }
                for item in businesses
            ]

        kakao_pages.side_effect = provide_photo
        web.side_effect = lambda businesses, mission, **kwargs: businesses

        result = enrich_place_businesses(
            [{
                "id": "12345",
                "name": "테스트소고기",
                "address": "경남 창원시 성산구 상남동",
                "place_url": "http://place.map.kakao.com/12345",
                "image_url": None,
            }],
            {"location": "창원시 상남동", "category": "소고기"},
            gpt_direct=True,
        )

        kakao_pages.assert_called_once()
        self.assertEqual(
            kakao_pages.call_args.args[0][0]["place_url"],
            "http://place.map.kakao.com/12345",
        )
        self.assertEqual(
            result[0]["image_url"],
            "https://t1.kakaocdn.net/place.jpg",
        )
