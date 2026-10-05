from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIClient


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["service"],
            "ARABA API",
        )

    @patch(
        "api.views.get_openai_status",
        return_value={
            "configured": True,
            "masked": "sk-test••••••••••••1234",
        },
    )
    def test_openai_status_uses_request_key(
        self,
        mocked_status,
    ):
        response = self.client.get(
            "/api/settings/openai/",
            HTTP_X_OPENAI_API_KEY="sk-test-1234",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["configured"])
        mocked_status.assert_called_once_with(
            "sk-test-1234"
        )

    def test_openai_save_is_not_persisted_server_side(self):
        response = self.client.post(
            "/api/settings/openai/save/",
            {"api_key": "sk-test"},
            format="json",
        )

        self.assertEqual(response.status_code, 410)
        self.assertFalse(response.data["ok"])


class MissionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(
        "api.services.mission_service.create_mission"
    )
    def test_mission_create(
        self,
        mocked_create,
    ):
        mocked_create.return_value = {
            "title": "BMW X6 타이어 교체 알아보기",
            "summary": "창원에서 오늘 가능한 BMW X6 타이어 교체 업체를 가격 기준으로 비교",
            "category": "자동차",
            "location": "창원",
            "subject": "BMW X6 타이어 교체",
            "constraints": ["오늘 가능"],
            "comparison": "최저가격",
            "required_facts": [
                "업체명",
                "가격",
                "재고",
                "작업 가능시간",
            ],
            "needs_fresh_data": True,
            "may_need_phone_call": True,
            "missing_information": [],
            "clarification_questions": [],
            "ready_to_research": True,
        }

        response = self.client.post(
            "/api/missions/create/",
            {
                "request": (
                    "오늘 창원에서 BMW X6 타이어 "
                    "교체 가능한 가장 저렴한 곳 알아봐"
                )
            },
            format="json",
            HTTP_X_OPENAI_API_KEY="sk-test-1234",
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["mission"]["location"],
            "창원",
        )
        mocked_create.assert_called_once_with(
            "오늘 창원에서 BMW X6 타이어 교체 가능한 가장 저렴한 곳 알아봐",
            "sk-test-1234",
        )



class UpdateNotificationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_notify_update_requires_bearer_token(self):
        response = self.client.post(
            "/api/internal/notify-update/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["ok"])

    @patch(
        "api.services.update_notification_service."
        "send_update_notification",
        return_value="projects/araba-dev/messages/test",
    )
    @patch(
        "api.services.update_notification_service."
        "verify_github_actions_token",
        return_value={
            "repository": "kprism/araba",
            "ref": "refs/heads/main",
        },
    )
    def test_notify_update_sends_fcm_after_oidc_verification(
        self,
        mocked_verify,
        mocked_send,
    ):
        response = self.client.post(
            "/api/internal/notify-update/",
            {},
            format="json",
            HTTP_AUTHORIZATION="Bearer github-oidc-token",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        mocked_verify.assert_called_once_with(
            "github-oidc-token"
        )
        mocked_send.assert_called_once_with()



class NotificationRegistrationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(
        "api.services.update_notification_service."
        "subscribe_device_to_updates",
        return_value={
            "success_count": 1,
            "failure_count": 0,
            "topic": "araba-dev-updates",
        },
    )
    def test_register_notification_token(
        self,
        mocked_subscribe,
    ):
        token = "f" * 80

        response = self.client.post(
            "/api/notifications/register/",
            {"token": token},
            format="json",
            HTTP_X_KAKAO_REST_API_KEY="device-kakao-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["topic"],
            "araba-dev-updates",
        )
        mocked_subscribe.assert_called_once_with(token)

    def test_register_notification_token_requires_token(self):
        response = self.client.post(
            "/api/notifications/register/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["ok"])



class VoiceCallApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(
        "api.services.voice_call_service."
        "voice_configuration_status",
        return_value={
            "twilio_account_sid": True,
            "twilio_auth_token": True,
            "twilio_from_number": True,
            "voice_openai_key": True,
            "ready": True,
        },
    )
    def test_voice_status(self, mocked_status):
        response = self.client.get(
            "/api/voice/status/",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ready"])
        mocked_status.assert_called_once_with()

    def test_voice_test_call_requires_openai_key(self):
        response = self.client.post(
            "/api/voice/test-call/",
            {"phone_number": "010-1234-5678"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["ok"])

    @patch(
        "api.services.voice_call_service.start_test_call",
        return_value={
            "call_sid": "CATEST",
            "to": "+821012345678",
            "status": "queued",
        },
    )
    def test_voice_test_call_starts_outbound_call(
        self,
        mocked_call,
    ):
        response = self.client.post(
            "/api/voice/test-call/",
            {"phone_number": "010-1234-5678"},
            format="json",
            HTTP_X_OPENAI_API_KEY="sk-test",
            HTTP_X_TWILIO_ACCOUNT_SID="ACtest",
            HTTP_X_TWILIO_AUTH_TOKEN="twilio-test-token",
            HTTP_X_TWILIO_FROM_NUMBER="+12025550123",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["call_sid"],
            "CATEST",
        )
        mocked_call.assert_called_once_with(
            "010-1234-5678",
            account_sid="ACtest",
            auth_token="twilio-test-token",
            from_number="+12025550123",
            api_key="sk-test",
        )

    @patch(
        "api.services.voice_call_service.build_answer_twiml",
        return_value="<Response><Say>테스트</Say></Response>",
    )
    def test_voice_answer_returns_twiml(
        self,
        mocked_twiml,
    ):
        response = self.client.post(
            "/api/voice/answer/?session=signed-session",
            {},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "text/xml",
            response["Content-Type"],
        )
        mocked_twiml.assert_called_once_with(
            "signed-session"
        )

    @patch(
        "api.services.voice_call_service.build_response_twiml",
        return_value="<Response><Say>네</Say></Response>",
    )
    def test_voice_respond_passes_speech(
        self,
        mocked_twiml,
    ):
        response = self.client.post(
            (
                "/api/voice/respond/"
                "?session=signed-session"
                "&previous_response_id=resp_123"
            ),
            {"SpeechResult": "안녕하세요"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        mocked_twiml.assert_called_once_with(
            "signed-session",
            "안녕하세요",
            previous_response_id="resp_123",
        )


class VoiceCallServiceTests(TestCase):
    def test_normalize_twilio_from_number(self):
        from api.services.voice_call_service import (
            normalize_twilio_from_number,
        )

        self.assertEqual(
            normalize_twilio_from_number(
                "+1 (202) 555-0123"
            ),
            "+12025550123",
        )

    def test_normalize_korean_mobile_number(self):
        from api.services.voice_call_service import (
            normalize_phone_number,
        )

        self.assertEqual(
            normalize_phone_number(
                "010-1234-5678"
            ),
            "+821012345678",
        )



class LiveSessionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_live_session_requires_openai_key(self):
        response = self.client.post(
            "/api/live/session/",
            {"sdp": "v=0"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["ok"])

    @patch(
        "api.services.live_service.create_live_session",
        return_value={
            "session_id": "live_test",
            "sdp": "v=0\r\na=answer",
            "model": "gpt-live-1",
            "delegation": "client",
        },
    )
    def test_live_session_returns_webrtc_answer(
        self,
        mocked_create,
    ):
        response = self.client.post(
            "/api/live/session/",
            {"sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=ice-ufrag:test\r\na=ice-pwd:testpwd\r\n"},
            format="json",
            HTTP_X_OPENAI_API_KEY="sk-test",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["session_id"],
            "live_test",
        )
        self.assertEqual(
            response.data["model"],
            "gpt-live-1",
        )
        mocked_create.assert_called_once_with(
            "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=ice-ufrag:test\r\na=ice-pwd:testpwd\r\n",
            "sk-test",
        )



class LiveServiceTests(TestCase):
    @patch(
        "api.services.live_service.httpx.post"
    )
    @patch(
        "api.services.live_service.get_api_key",
        return_value="sk-test",
    )
    def test_live_service_preserves_offer_sdp_exactly(
        self,
        mocked_key,
        mocked_post,
    ):
        from api.services.live_service import create_live_session

        response = Mock()
        response.status_code = 201
        response.json.return_value = {
            "session": {"id": "live_test"},
            "transport": {
                "type": "webrtc",
                "sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n",
            },
        }
        mocked_post.return_value = response

        offer_sdp = (
            "v=0\r\n"
            "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
            "a=ice-ufrag:test\r\n"
            "a=ice-pwd:testpwd\r\n"
        )

        result = create_live_session(
            offer_sdp,
            "sk-test",
        )

        self.assertEqual(result["session_id"], "live_test")
        request_json = mocked_post.call_args.kwargs["json"]
        self.assertEqual(
            request_json["transport"]["sdp"],
            offer_sdp,
        )
        self.assertTrue(
            request_json["transport"]["sdp"].endswith("\r\n")
        )
        mocked_key.assert_called_once_with("sk-test")

    @patch(
        "api.services.live_service.httpx.post"
    )
    def test_live_service_rejects_incomplete_sdp(
        self,
        mocked_post,
    ):
        from api.services.live_service import (
            LiveConfigurationError,
            create_live_session,
        )

        with self.assertRaises(LiveConfigurationError):
            create_live_session(
                "v=0\r\n",
                "sk-test",
            )

        mocked_post.assert_not_called()


class ResearchSearchApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(
        "api.services.research_service._kakao_rest_api_key",
        return_value="server-fallback-key",
    )
    @patch(
        "api.services.research_service.httpx.get"
    )
    def test_research_search_uses_request_kakao_key(
        self,
        mocked_get,
        mocked_server_key,
    ):
        kakao_response = Mock()
        kakao_response.status_code = 200
        kakao_response.json.return_value = {
            "meta": {
                "total_count": 1,
            },
            "documents": [
                {
                    "id": "12345",
                    "place_name": "창원타이어 실제업체",
                    "category_name": "자동차 > 자동차정비 > 타이어",
                    "phone": "055-123-4567",
                    "address_name": "경남 창원시 성산구 테스트동 1",
                    "road_address_name": "경남 창원시 성산구 테스트로 1",
                    "x": "128.681",
                    "y": "35.228",
                    "place_url": "http://place.map.kakao.com/12345",
                }
            ],
        }
        mocked_get.return_value = kakao_response

        response = self.client.post(
            "/api/research/search/",
            {
                "mission": {
                    "category": "자동차",
                    "location": "창원",
                    "subject": "BMW S6 타이어 교체",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(response.data["source"], "kakao")
        self.assertEqual(len(response.data["businesses"]), 1)
        self.assertEqual(
            response.data["businesses"][0]["name"],
            "창원타이어 실제업체",
        )
        self.assertEqual(
            response.data["businesses"][0]["phone"],
            "055-123-4567",
        )
        self.assertEqual(
            response.data["businesses"][0]["source"],
            "kakao",
        )
        self.assertTrue(response.data["phone_call_mock"])
        self.assertTrue(response.data["life_info"])

        mocked_server_key.assert_not_called()
        mocked_get.assert_called_once()
        request_kwargs = mocked_get.call_args.kwargs
        self.assertEqual(
            request_kwargs["headers"]["Authorization"],
            "KakaoAK device-kakao-key",
        )
        self.assertEqual(
            request_kwargs["params"]["query"],
            "창원 BMW S6 타이어 교체",
        )

    @patch(
        "api.services.research_service._kakao_rest_api_key",
        return_value="",
    )
    def test_research_search_requires_kakao_key(
        self,
        mocked_key,
    ):
        response = self.client.post(
            "/api/research/search/",
            {
                "mission": {
                    "category": "자동차",
                    "location": "창원",
                    "subject": "타이어",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.data["ok"])
        self.assertIn(
            "Kakao REST API Key",
            response.data["message"],
        )
        mocked_key.assert_called_once_with()

    def test_research_search_requires_mission(self):
        response = self.client.post(
            "/api/research/search/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["ok"])
