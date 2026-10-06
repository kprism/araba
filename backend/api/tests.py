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
            caller_id_number=None,
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
    @patch(
        "api.services.voice_call_service.httpx.post"
    )
    def test_trial_fallback_omits_from_parameter(
        self,
        mocked_post,
    ):
        from api.services.voice_call_service import (
            TRIAL_SPEECH_RECOGNITION_URL,
            _create_trial_template_call,
        )

        response = Mock()
        response.status_code = 201
        response.json.return_value = {
            "sid": "CATRIAL",
            "status": "queued",
        }
        response.text = ""
        mocked_post.return_value = response

        result = _create_trial_template_call(
            account_sid="ACtest",
            auth_token="token",
            to_number="+821012345678",
        )

        self.assertEqual(
            result["call_sid"],
            "CATRIAL",
        )
        self.assertTrue(result["trial_fallback"])
        request_kwargs = mocked_post.call_args.kwargs
        self.assertEqual(
            request_kwargs["data"],
            {
                "To": "+821012345678",
                "Url": TRIAL_SPEECH_RECOGNITION_URL,
            },
        )
        self.assertNotIn(
            "From",
            request_kwargs["data"],
        )
        self.assertEqual(
            request_kwargs["auth"],
            ("ACtest", "token"),
        )

    @patch(
        "api.services.voice_call_service.Client"
    )
    def test_verified_user_number_is_preferred_as_caller_id(
        self,
        mocked_client_class,
    ):
        from api.services.voice_call_service import (
            start_test_call,
        )

        call = Mock()
        call.sid = "CACALLER"
        call.status = "queued"
        client = Mock()
        client.calls.create.return_value = call
        mocked_client_class.return_value = client

        result = start_test_call(
            "010-9999-8888",
            account_sid="ACtest",
            auth_token="token",
            from_number="+17372508034",
            caller_id_number="010-1234-5678",
            api_key="sk-test",
        )

        self.assertEqual(
            result["caller_id"],
            "+821012345678",
        )
        client.calls.create.assert_called_once()
        request_kwargs = client.calls.create.call_args.kwargs
        self.assertEqual(
            request_kwargs["to"],
            "+821099998888",
        )
        self.assertEqual(
            request_kwargs["from_"],
            "+821012345678",
        )

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



class LiveTelephonyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(
        "api.services.live_service.live_telephony_status",
        return_value={
            "ready": True,
            "transport": "sip",
            "model": "gpt-live-1",
            "missing": [],
            "provider_url_valid": True,
            "caller_number_configured": True,
        },
    )
    def test_live_telephony_status(
        self,
        mocked_status,
    ):
        response = self.client.get(
            "/api/live/telephony/status/",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ready"])
        self.assertEqual(
            response.data["transport"],
            "sip",
        )
        mocked_status.assert_called_once_with()

    def test_live_outbound_call_requires_openai_key(self):
        response = self.client.post(
            "/api/live/outbound-call/",
            {
                "phone_number": "010-1234-5678",
                "purpose": "내일 오후 3시 타이어 교체 예약",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["ok"])

    @patch(
        "api.services.live_service.create_outbound_live_call",
        return_value={
            "session_id": "live_phone_1",
            "destination": "+821012345678",
            "caller_number": "+82105556666",
            "transport": "sip",
            "model": "gpt-live-1",
            "status": "initializing",
        },
    )
    def test_live_outbound_call_starts_session(
        self,
        mocked_call,
    ):
        response = self.client.post(
            "/api/live/outbound-call/",
            {
                "phone_number": "010-1234-5678",
                "purpose": "내일 오후 3시 타이어 교체 예약",
                "business_name": "테스트타이어",
                "requested_time": "내일 오후 3시",
                "reservation_name": "홍길동",
                "notes": "BMW X6",
                "voice_gender": "female",
                "voice_speed": "medium",
            },
            format="json",
            HTTP_X_OPENAI_API_KEY="sk-test",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["session_id"],
            "live_phone_1",
        )
        mocked_call.assert_called_once_with(
            "010-1234-5678",
            api_key="sk-test",
            purpose="내일 오후 3시 타이어 교체 예약",
            business_name="테스트타이어",
            requested_time="내일 오후 3시",
            reservation_name="홍길동",
            notes="BMW X6",
            voice_gender="female",
            voice_speed="medium",
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



class LiveTelephonyServiceTests(TestCase):
    @patch.dict(
        "os.environ",
        {
            "ARABA_SIP_PROVIDER_URL": "sips:sip.example.com:5061",
            "ARABA_SIP_USERNAME": "sip-user",
            "ARABA_SIP_PASSWORD": "sip-pass",
            "ARABA_SIP_CALLER_NUMBER": "02-1234-5678",
        },
        clear=False,
    )
    @patch(
        "api.services.live_service.httpx.post"
    )
    def test_create_outbound_live_call_uses_sip_transport(
        self,
        mocked_post,
    ):
        from api.services.live_service import (
            create_outbound_live_call,
        )

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "session": {
                "id": "live_sip_123",
            },
            "transport": {
                "type": "sip",
            },
        }
        mocked_post.return_value = response

        result = create_outbound_live_call(
            "055-123-4567",
            api_key="sk-test",
            purpose="내일 영업 여부 확인 후 예약",
            business_name="테스트타이어",
            requested_time="내일 오후",
            reservation_name="홍길동",
            notes="BMW X6 타이어 교체",
        )

        self.assertEqual(
            result["session_id"],
            "live_sip_123",
        )
        self.assertEqual(
            result["destination"],
            "+82551234567",
        )
        self.assertEqual(
            result["caller_number"],
            "+82212345678",
        )

        request_kwargs = mocked_post.call_args.kwargs
        payload = request_kwargs["json"]
        self.assertEqual(
            payload["transport"]["type"],
            "sip",
        )
        self.assertEqual(
            payload["transport"]["destination"],
            "+82551234567",
        )
        self.assertEqual(
            payload["transport"]["trunk"]["provider_url"],
            "sips:sip.example.com:5061",
        )
        self.assertEqual(
            payload["transport"]["trunk"]["auth"],
            {
                "type": "digest",
                "username": "sip-user",
                "password": "sip-pass",
            },
        )
        self.assertEqual(
            payload["transport"]["trunk"]["caller_number"],
            "+82212345678",
        )
        self.assertEqual(
            payload["session"]["model"],
            "gpt-live-1",
        )
        self.assertEqual(
            payload["session"]["delegation"]["type"],
            "responses",
        )
        self.assertIn(
            "내일 영업 여부 확인 후 예약",
            payload["session"]["instructions"],
        )

    @patch.dict(
        "os.environ",
        {},
        clear=True,
    )
    def test_live_telephony_status_reports_missing_sip_config(
        self,
    ):
        from api.services.live_service import (
            live_telephony_status,
        )

        result = live_telephony_status()

        self.assertFalse(result["ready"])
        self.assertIn(
            "ARABA_SIP_PROVIDER_URL",
            result["missing"],
        )
        self.assertIn(
            "ARABA_SIP_USERNAME",
            result["missing"],
        )
        self.assertIn(
            "ARABA_SIP_PASSWORD",
            result["missing"],
        )
        self.assertIn(
            "ARABA_SIP_CALLER_NUMBER",
            result["missing"],
        )

    def test_normalize_live_phone_number_supports_landline(self):
        from api.services.live_service import (
            normalize_live_phone_number,
        )

        self.assertEqual(
            normalize_live_phone_number(
                "055-123-4567"
            ),
            "+82551234567",
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


class MissionScopeTests(TestCase):
    def test_broad_category_request_clears_stale_specific_business(self):
        from api.services.mission_service import (
            _normalize_search_scope,
        )

        mission = {
            "search_mode": "follow_up_detail",
            "target_business": "처음말한치과",
            "ready_to_research": True,
        }

        result = _normalize_search_scope(
            mission,
            """
[대화 문맥 - 참고용]
{"target_business":"처음말한치과","category":"의료","location":"창원시 의창구 중동"}
[현재 요청]
창원시 의창구 중동에 치과 찾아줘
""".strip(),
        )

        self.assertIsNone(
            result["target_business"]
        )
        self.assertEqual(
            result["search_mode"],
            "category_discovery",
        )

    def test_follow_up_pronoun_keeps_selected_business(self):
        from api.services.mission_service import (
            _normalize_search_scope,
        )

        mission = {
            "search_mode": "",
            "target_business": "처음말한치과",
            "ready_to_research": True,
        }

        result = _normalize_search_scope(
            mission,
            """
[대화 문맥 - 참고용]
{"target_business":"처음말한치과"}
[현재 요청]
그 치과 영업시간은?
""".strip(),
        )

        self.assertEqual(
            result["target_business"],
            "처음말한치과",
        )
        self.assertEqual(
            result["search_mode"],
            "follow_up_detail",
        )

    def test_explicit_new_business_becomes_exact_place(self):
        from api.services.mission_service import (
            _normalize_search_scope,
        )

        mission = {
            "search_mode": "general",
            "target_business": "새봄치과",
            "ready_to_research": True,
        }

        result = _normalize_search_scope(
            mission,
            """
[대화 문맥 - 참고용]
{"target_business":"처음말한치과"}
[현재 요청]
새봄치과 찾아줘
""".strip(),
        )

        self.assertEqual(
            result["target_business"],
            "새봄치과",
        )
        self.assertEqual(
            result["search_mode"],
            "exact_place",
        )


class NaverPlaceServiceTests(TestCase):
    @patch(
        "api.services.naver_place_service.httpx.get"
    )
    def test_naver_place_matches_same_business_and_reads_json_ld(
        self,
        mocked_get,
    ):
        from api.services.naver_place_service import (
            enrich_one_business,
        )

        search_response = Mock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "items": [
                {
                    "title": "<b>이루다헤어</b>",
                    "link": "https://m.place.naver.com/place/123",
                    "category": "생활,편의>미용실",
                    "address": "경남 창원시 의창구 중동 1",
                    "roadAddress": "경남 창원시 의창구 중동로 10",
                }
            ]
        }

        page_response = Mock()
        page_response.status_code = 200
        page_response.url = (
            "https://m.place.naver.com/place/123"
        )
        page_response.text = """
        <html>
          <head>
            <title>이루다헤어 : 네이버</title>
            <meta property="og:description"
                  content="창원 중동 미용실" />
            <script type="application/ld+json">
            {
              "@type": "HairSalon",
              "name": "이루다헤어",
              "openingHours": ["Mo-Fr 10:00-20:00"],
              "offers": [
                {
                  "name": "남성컷",
                  "price": "20000",
                  "priceCurrency": "KRW"
                }
              ]
            }
            </script>
          </head>
        </html>
        """

        mocked_get.side_effect = [
            search_response,
            page_response,
        ]

        result = enrich_one_business(
            {
                "name": "이루다헤어",
                "category": "가정,생활 > 미용 > 미용실",
                "address": "경남 창원시 의창구 중동로 10",
                "road_address": "경남 창원시 의창구 중동로 10",
            },
            client_id="naver-id",
            client_secret="naver-secret",
        )

        self.assertTrue(result["naver"]["matched"])
        self.assertTrue(
            result["naver"]["page_checked"]
        )
        self.assertEqual(
            result["naver"]["opening_hours"],
            ["Mo-Fr 10:00-20:00"],
        )
        self.assertEqual(
            result["naver"]["prices"][0]["price"],
            "20000",
        )

    @patch(
        "api.services.naver_place_service.httpx.get"
    )
    def test_naver_place_photo_is_used_when_kakao_photo_missing(
        self,
        mocked_get,
    ):
        from api.services.naver_place_service import (
            enrich_one_business,
        )

        search_response = Mock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "items": [
                {
                    "title": "<b>기와야순두부 창원중동점</b>",
                    "link": "https://m.place.naver.com/place/123",
                    "category": "한식>두부요리",
                    "address": "경남 창원시 의창구 중동",
                    "roadAddress": "경남 창원시 의창구 평산로204번길 7",
                }
            ]
        }

        page_response = Mock()
        page_response.status_code = 200
        page_response.url = (
            "https://m.place.naver.com/place/123"
        )
        page_response.text = """
        <html>
          <head>
            <meta property="og:image"
                  content="https://search.pstatic.net/common/?src=test.jpg" />
          </head>
        </html>
        """
        mocked_get.side_effect = [
            search_response,
            page_response,
        ]

        result = enrich_one_business(
            {
                "name": "기와야순두부 창원중동점",
                "category": "음식점 > 한식 > 두부요리",
                "address": "경남 창원시 의창구 평산로204번길 7",
                "road_address": "경남 창원시 의창구 평산로204번길 7",
                "image_url": None,
            },
            client_id="naver-id",
            client_secret="naver-secret",
        )

        self.assertEqual(
            result["image_url"],
            "https://search.pstatic.net/common/?src=test.jpg",
        )
        self.assertEqual(
            result["image_source"],
            "naver_place",
        )

    def test_naver_enrichment_is_optional_without_credentials(
        self,
    ):
        from api.services.naver_place_service import (
            enrich_businesses_with_naver,
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ):
            result = enrich_businesses_with_naver(
                [
                    {
                        "name": "테스트미용실",
                    }
                ]
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["naver"]["status"],
            "not_configured",
        )


class KakaoPlaceServiceTests(TestCase):
    @patch(
        "api.services.kakao_place_service.httpx.get"
    )
    def test_kakao_place_extracts_registered_photo(
        self,
        mocked_get,
    ):
        from api.services.kakao_place_service import (
            inspect_kakao_place_page,
        )

        response = Mock()
        response.status_code = 200
        response.url = (
            "https://place.map.kakao.com/12345"
        )
        response.text = """
        <html>
          <head>
            <meta property="og:image"
                  content="https://img1.kakaocdn.net/cthumb/local/C544x320.q50/?fname=test.jpg" />
          </head>
        </html>
        """
        mocked_get.return_value = response

        result = inspect_kakao_place_page(
            "https://place.map.kakao.com/12345"
        )

        self.assertTrue(result["checked"])
        self.assertEqual(
            result["image_url"],
            "https://img1.kakaocdn.net/cthumb/local/C544x320.q50/?fname=test.jpg",
        )

    @patch(
        "api.services.kakao_place_service.httpx.get"
    )
    def test_kakao_place_rejects_non_kakao_image(
        self,
        mocked_get,
    ):
        from api.services.kakao_place_service import (
            inspect_kakao_place_page,
        )

        response = Mock()
        response.status_code = 200
        response.url = (
            "https://place.map.kakao.com/12345"
        )
        response.text = """
        <meta property="og:image"
              content="https://example.com/not-kakao.jpg" />
        """
        mocked_get.return_value = response

        result = inspect_kakao_place_page(
            "https://place.map.kakao.com/12345"
        )

        self.assertTrue(result["checked"])
        self.assertIsNone(result["image_url"])


class ResearchSearchApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.kakao_page_enrich_patcher = patch(
            "api.services.research_service."
            "enrich_businesses_with_kakao_pages",
            side_effect=lambda businesses: businesses,
        )
        self.mocked_kakao_page_enrich = (
            self.kakao_page_enrich_patcher.start()
        )
        self.addCleanup(
            self.kakao_page_enrich_patcher.stop
        )

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
        origin_response = Mock()
        origin_response.status_code = 200
        origin_response.json.return_value = {
            "documents": [
                {
                    "x": "128.681",
                    "y": "35.228",
                    "address": {
                        "address_name": "경남 창원시",
                    },
                }
            ],
        }

        search_response = Mock()
        search_response.status_code = 200
        search_response.json.return_value = {
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
        mocked_get.side_effect = [
            origin_response,
            search_response,
        ]

        response = self.client.post(
            "/api/research/search/",
            {
                "mission": {
                    "category": "자동차",
                    "location": "창원",
                    "subject": "BMW S6 타이어 교체",
                    "search_terms": ["타이어"],
                    "subcategories": ["타이어"],
                }
            },
            format="json",
            HTTP_X_KAKAO_REST_API_KEY="device-kakao-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(response.data["source"], "kakao+naver")
        self.assertEqual(
            response.data["primary_source"],
            "kakao",
        )
        self.assertEqual(
            response.data["secondary_source"],
            "naver_place",
        )
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
        self.assertEqual(
            mocked_get.call_count,
            2,
        )
        origin_kwargs = mocked_get.call_args_list[0].kwargs
        self.assertEqual(
            origin_kwargs["headers"]["Authorization"],
            "KakaoAK device-kakao-key",
        )
        self.assertEqual(
            origin_kwargs["params"]["query"],
            "창원시",
        )
        search_kwargs = mocked_get.call_args_list[1].kwargs
        self.assertEqual(
            search_kwargs["params"]["query"],
            "경남 창원시 타이어",
        )
        self.assertEqual(
            search_kwargs["params"]["size"],
            8,
        )

    @patch(
        "api.services.research_service.httpx.get"
    )
    def test_research_search_canonicalizes_neighborhood_and_compacts_term(
        self,
        mocked_get,
    ):
        origin_response = Mock()
        origin_response.status_code = 200
        origin_response.json.return_value = {
            "documents": [
                {
                    "x": "128.6500",
                    "y": "35.2600",
                    "address": {
                        "address_name": "경남 창원시 의창구 중동",
                    },
                }
            ],
        }

        search_response = Mock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "documents": [
                {
                    "id": "54321",
                    "place_name": "중동 타이어",
                    "category_name": "자동차 > 자동차정비 > 타이어",
                    "phone": "055-555-5555",
                    "address_name": "경남 창원시 의창구 중동",
                    "road_address_name": "경남 창원시 의창구 중동로 1",
                    "x": "128.65",
                    "y": "35.26",
                    "place_url": "http://place.map.kakao.com/54321",
                }
            ],
        }

        mocked_get.side_effect = [
            origin_response,
            search_response,
        ]

        response = self.client.post(
            "/api/research/search/",
            {
                "mission": {
                    "category": "자동차",
                    "location": "의창구 중동",
                    "subject": "타이어 수리점",
                    "search_terms": ["타이어 수리점"],
                    "subcategories": ["타이어"],
                }
            },
            format="json",
            HTTP_X_KAKAO_REST_API_KEY="device-kakao-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["search_query"],
            "경남 창원시 의창구 중동 타이어",
        )
        self.assertEqual(
            response.data["businesses"][0]["name"],
            "중동 타이어",
        )
        search_kwargs = mocked_get.call_args_list[1].kwargs
        self.assertEqual(
            search_kwargs["params"]["query"],
            "경남 창원시 의창구 중동 타이어",
        )

    def test_location_filter_rejects_same_name_outside_requested_region(self):
        from api.services.research_service import (
            _matches_location,
        )

        requested = "경남 창원시 의창구"

        changwon = {
            "place_name": "삼거리식당",
            "address_name": "경남 창원시 의창구 북면 테스트리 1",
            "road_address_name": "경남 창원시 의창구 테스트로 10",
        }
        jeju = {
            "place_name": "삼거리식당",
            "address_name": "제주특별자치도 제주시 애월읍 테스트리 1",
            "road_address_name": "제주특별자치도 제주시 테스트로 10",
        }
        gangwon = {
            "place_name": "삼거리식당",
            "address_name": "강원특별자치도 강릉시 테스트동 1",
            "road_address_name": "강원특별자치도 강릉시 테스트로 10",
        }

        self.assertTrue(
            _matches_location(
                changwon,
                requested,
            )
        )
        self.assertFalse(
            _matches_location(
                jeju,
                requested,
            )
        )
        self.assertFalse(
            _matches_location(
                gangwon,
                requested,
            )
        )

    def test_target_business_filter_keeps_exact_named_place_only(self):
        from api.services.research_service import (
            _matches_target_business,
        )

        mission = {
            "target_business": "삼거리 식당",
        }

        self.assertTrue(
            _matches_target_business(
                {
                    "place_name": "삼거리식당 본점",
                },
                mission,
            )
        )
        self.assertFalse(
            _matches_target_business(
                {
                    "place_name": "삼거리횟집",
                },
                mission,
            )
        )

    def test_relevance_filter_rejects_same_neighborhood_apartment(self):
        from api.services.research_service import (
            _matches_mission,
        )

        mission = {
            "category": "자동차",
            "location": "경남 창원시 의창구 중동",
            "subject": "타이어 수리점",
            "search_terms": ["중동 타이어 수리점"],
            "subcategories": ["타이어"],
        }

        apartment = {
            "place_name": "창원중동유니시티1단지아파트",
            "category_name": "부동산 > 주거 > 아파트",
        }
        tire_shop = {
            "place_name": "중동타이어",
            "category_name": "자동차 > 자동차정비 > 타이어",
        }

        self.assertFalse(
            _matches_mission(apartment, mission)
        )
        self.assertTrue(
            _matches_mission(tire_shop, mission)
        )

    def test_relevance_filter_is_generic_for_hair_salon(self):
        from api.services.research_service import (
            _matches_mission,
        )

        mission = {
            "category": "뷰티",
            "location": "경남 창원시 의창구 중동",
            "subject": "미용실",
            "search_terms": ["중동 미용실"],
            "subcategories": ["미용실"],
        }

        apartment = {
            "place_name": "중동센트럴아파트",
            "category_name": "부동산 > 주거 > 아파트",
        }
        salon = {
            "place_name": "헤어봄",
            "category_name": "가정,생활 > 미용 > 미용실",
        }

        self.assertFalse(
            _matches_mission(apartment, mission)
        )
        self.assertTrue(
            _matches_mission(salon, mission)
        )

    def test_category_discovery_queries_category_not_stale_business(self):
        from api.services.research_service import (
            _search_queries,
        )

        queries = _search_queries(
            {
                "search_mode": "category_discovery",
                "category": "의료",
                "subcategories": ["치과"],
                "location": "경남 창원시 의창구 중동",
                "location_explicit": True,
                "subject": "치과",
                "target_business": "처음말한치과",
                "search_terms": ["치과"],
            }
        )

        self.assertTrue(queries)
        self.assertIn(
            "경남 창원시 의창구 중동 치과",
            queries,
        )
        self.assertFalse(
            any(
                "처음말한치과" in query
                for query in queries
            )
        )

    def test_category_discovery_ignores_stale_specific_business(self):
        from api.services.research_service import (
            _effective_target_business,
            _matches_mission,
        )

        mission = {
            "search_mode": "category_discovery",
            "category": "의료",
            "subcategories": ["치과"],
            "location": "경남 창원시 의창구 중동",
            "subject": "치과",
            "target_business": "이전에말한특정치과",
            "search_terms": ["치과"],
        }

        another_dentist = {
            "place_name": "중동스마트치과",
            "category_name": "의료,건강 > 병원 > 치과",
            "address_name": "경남 창원시 의창구 중동",
            "road_address_name": "경남 창원시 의창구 중동로 10",
        }

        self.assertEqual(
            _effective_target_business(mission),
            "",
        )
        self.assertTrue(
            _matches_mission(
                another_dentist,
                mission,
            )
        )

    def test_follow_up_detail_keeps_selected_business(self):
        from api.services.research_service import (
            _effective_target_business,
        )

        mission = {
            "search_mode": "follow_up_detail",
            "target_business": "중동스마트치과",
        }

        self.assertEqual(
            _effective_target_business(mission),
            "중동스마트치과",
        )

    def test_exact_named_place_ignores_stale_category_and_neighborhood(self):
        from api.services.research_service import (
            _matches_location,
            _matches_mission,
        )

        mission = {
            "category": "음식점",
            "subcategories": ["식당"],
            "location": "경남 창원시 의창구 중동",
            "location_explicit": False,
            "subject": "의창구청",
            "target_business": "의창구청",
            "search_terms": ["식당"],
        }
        office = {
            "place_name": "의창구청",
            "category_name": "사회,공공기관 > 지방행정기관 > 구청",
            "address_name": "경남 창원시 의창구 도계동 263-2",
            "road_address_name": "경남 창원시 의창구 태복산로15번길 8",
        }

        self.assertTrue(
            _matches_mission(
                office,
                mission,
            )
        )
        self.assertFalse(
            _matches_location(
                office,
                mission["location"],
            )
        )

    def test_exact_named_place_without_new_location_searches_name_first(self):
        from api.services.research_service import (
            _search_queries,
        )

        queries = _search_queries(
            {
                "category": "음식점",
                "subcategories": ["식당"],
                "location": "경남 창원시 의창구 중동",
                "location_explicit": False,
                "subject": "의창구청",
                "target_business": "의창구청",
                "search_terms": ["식당"],
            }
        )

        self.assertEqual(
            queries[0],
            "의창구청",
        )
        self.assertIn(
            "경남 창원시 의창구 중동 의창구청",
            queries,
        )
        self.assertNotIn(
            "경남 창원시 의창구 중동 식당",
            queries,
        )

    def test_exact_named_place_with_new_location_keeps_location_scope(self):
        from api.services.research_service import (
            _search_queries,
        )

        queries = _search_queries(
            {
                "location": "경남 창원시 의창구",
                "location_explicit": True,
                "target_business": "삼거리식당",
            }
        )

        self.assertEqual(
            queries[0],
            "경남 창원시 의창구 삼거리식당",
        )

    def test_search_queries_prioritize_exact_target_business(self):
        from api.services.research_service import (
            _search_queries,
        )

        queries = _search_queries(
            {
                "category": "미용실",
                "location": "경남 창원시 의창구 중동",
                "location_explicit": True,
                "subject": "이루다헤어 영업시간",
                "target_business": "이루다헤어",
                "search_terms": ["이루다헤어", "미용실"],
                "subcategories": ["미용실"],
            }
        )

        self.assertTrue(queries)
        self.assertEqual(
            queries[0],
            "경남 창원시 의창구 중동 이루다헤어",
        )

    def test_search_queries_keep_parent_region_fallbacks(self):
        from api.services.research_service import (
            _search_queries,
        )

        queries = _search_queries(
            {
                "category": "자동차",
                "location": "경남 창원시 의창구 중동",
                "subject": "타이어 수리점",
                "search_terms": [
                    "타이어 수리점",
                    "타이어 교체",
                    "자동차 타이어 정비",
                    "타이어 전문점",
                ],
                "subcategories": ["타이어"],
            }
        )

        self.assertIn(
            "경남 창원시 의창구 중동 타이어",
            queries,
        )
        self.assertIn(
            "경남 창원시 의창구 타이어",
            queries,
        )
        self.assertLessEqual(len(queries), 8)

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


class MockCallComparisonApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_mock_call_compare_ranks_by_effective_cost(self):
        response = self.client.post(
            "/api/research/mock-call/",
            {
                "mission": {
                    "category": "자동차",
                    "location": "창원",
                    "subject": "BMW X6 타이어 두 개 교체",
                    "constraints": ["오늘 가능"],
                },
                "businesses": [
                    {
                        "id": "101",
                        "name": "A타이어",
                        "latitude": "35.2200",
                        "longitude": "128.6800",
                        "address": "창원시 성산구",
                    },
                    {
                        "id": "102",
                        "name": "B타이어",
                        "latitude": "35.2300",
                        "longitude": "128.6900",
                        "address": "창원시 의창구",
                    },
                    {
                        "id": "103",
                        "name": "C타이어",
                        "latitude": "35.2400",
                        "longitude": "128.7000",
                        "address": "창원시 마산회원구",
                    },
                ],
                "origin": {
                    "label": "경남 창원시",
                    "latitude": "35.2285",
                    "longitude": "128.6818",
                    "source": "user_search_region",
                    "accuracy": "region_reference",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertTrue(response.data["mock"])
        self.assertEqual(len(response.data["businesses"]), 3)
        self.assertEqual(
            response.data["businesses"][0]["economic_rank"],
            1,
        )
        self.assertIn(
            "mock_total_price",
            response.data["businesses"][0],
        )
        self.assertIn(
            "effective_cost",
            response.data["businesses"][0],
        )
        self.assertIn(
            "time_cost_estimate",
            response.data["businesses"][0],
        )
        self.assertIn(
            "total_time_minutes",
            response.data["businesses"][0],
        )
        self.assertTrue(
            response.data["businesses"][0]["mock_questions"]
        )
        self.assertEqual(
            response.data["reference_origin"]["source"],
            "user_search_region",
        )
        self.assertEqual(
            response.data["recommendation"]["name"],
            response.data["businesses"][0]["name"],
        )
        self.assertIsInstance(
            response.data["record_id"],
            int,
        )

    def test_mock_call_never_invents_unverified_price(self):
        response = self.client.post(
            "/api/research/mock-call/",
            {
                "mission": {
                    "category": "미용실",
                    "intent": "예약",
                    "subject": "커트 예약",
                    "required_facts": [
                        "가격",
                        "가능한 예약시간대",
                    ],
                },
                "businesses": [
                    {
                        "id": "salon-1",
                        "name": "테스트미용실",
                        "latitude": "35.2200",
                        "longitude": "128.6800",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        business = response.data["businesses"][0]
        self.assertIsNone(
            business["mock_total_price"]
        )
        self.assertIsNone(
            business["effective_cost"]
        )
        self.assertIsInstance(
            business["efficiency_score"],
            int,
        )
        self.assertIn(
            "실제 가격 미확인",
            response.data["recommendation"]["reason"],
        )

    def test_mock_call_uses_verified_price_when_present(self):
        response = self.client.post(
            "/api/research/mock-call/",
            {
                "mission": {
                    "category": "미용실",
                    "intent": "예약",
                    "subject": "커트 예약",
                    "required_facts": ["가격"],
                },
                "businesses": [
                    {
                        "id": "salon-2",
                        "name": "가격확인미용실",
                        "verified_total_price": 25000,
                        "latitude": "35.2200",
                        "longitude": "128.6800",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        business = response.data["businesses"][0]
        self.assertEqual(
            business["mock_total_price"],
            25000,
        )
        self.assertIsInstance(
            business["effective_cost"],
            int,
        )

    def test_mock_call_compare_supports_dynamic_category(self):
        response = self.client.post(
            "/api/research/mock-call/",
            {
                "mission": {
                    "category": "미용실",
                    "subcategories": ["헤어컷"],
                    "intent": "예약",
                    "subject": "오늘 머리 자르기",
                    "attributes": {
                        "예약시간": "미정",
                    },
                    "required_facts": [
                        "가능한 예약시간대",
                        "최종 결제금액",
                    ],
                    "comparison": "가장빠른가능시간",
                },
                "businesses": [
                    {
                        "id": "1",
                        "name": "테스트미용실",
                        "latitude": "35.2200",
                        "longitude": "128.6800",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertTrue(
            response.data["businesses"][0]["mock_available_slots"]
        )
        self.assertTrue(
            response.data["recommendation"]["available_slots"]
        )


class ResearchHistoryApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_history_groups_saved_mock_research(self):
        create_response = self.client.post(
            "/api/research/mock-call/",
            {
                "mission": {
                    "category": "자동차",
                    "location": "창원",
                    "subject": "BMW X6 타이어 두 개 교체",
                    "constraints": ["오늘 가능"],
                },
                "businesses": [
                    {
                        "id": "201",
                        "name": "창원타이어A",
                        "latitude": "35.2200",
                        "longitude": "128.6800",
                        "address": "창원시 성산구",
                    },
                    {
                        "id": "202",
                        "name": "창원타이어B",
                        "latitude": "35.2300",
                        "longitude": "128.6900",
                        "address": "창원시 의창구",
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            200,
        )

        response = self.client.get(
            "/api/research/history/",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(
            response.data["total_count"],
            1,
        )
        self.assertEqual(
            response.data["categories"][0]["category"],
            "자동차",
        )
        record = response.data["categories"][0]["records"][0]
        self.assertEqual(
            record["subject"],
            "BMW X6 타이어 두 개 교체",
        )
        self.assertEqual(
            record["location"],
            "창원",
        )
        self.assertTrue(
            record["recommendation"]["name"],
        )
        self.assertEqual(
            record["business_count"],
            2,
        )
        self.assertEqual(
            len(record["businesses"]),
            2,
        )
        self.assertTrue(
            record["businesses"][0]["mock_questions"],
        )


class ResearchRelevanceFilterTests(TestCase):
    def test_tire_research_filters_unrelated_restaurant(self):
        from api.services.research_service import _matches_mission

        mission = {
            "category": "자동차",
            "subject": "BMW X6 타이어 교체",
        }

        restaurant = {
            "place_name": "창원맛집",
            "category_name": "음식점 > 한식",
        }
        tire_shop = {
            "place_name": "창원타이어",
            "category_name": "자동차 > 자동차정비 > 타이어",
        }

        self.assertFalse(
            _matches_mission(restaurant, mission)
        )
        self.assertTrue(
            _matches_mission(tire_shop, mission)
        )



class DynamicResearchFilterTests(TestCase):
    def test_filters_are_created_from_actual_saved_data(self):
        from api.models import ResearchRecord
        from api.services.research_record_service import (
            list_research_records_grouped,
        )

        ResearchRecord.objects.create(
            category="미용실",
            subject="헤어컷 예약",
            location="창원",
            mission={
                "category": "미용실",
                "subcategories": ["헤어컷"],
                "intent": "예약",
                "comparison": "가장빠른가능시간",
                "attributes": {
                    "스타일": "남성컷",
                },
            },
            businesses=[],
            recommendation={},
        )

        result = list_research_records_grouped()
        filters = result["filters"]

        self.assertEqual(
            filters["categories"][0]["value"],
            "미용실",
        )

        sections = filters["by_category"]["미용실"]["sections"]
        labels = [
            item["label"]
            for item in sections
        ]

        self.assertIn("세부 분류", labels)
        self.assertIn("지역", labels)
        self.assertIn("목적", labels)
        self.assertIn("스타일", labels)


class GoalFirstIntentBrainTests(TestCase):
    def test_enhance_mission_adds_answer_blueprint_without_breaking_legacy_fields(
        self,
    ):
        from api.services.intent_brain_service import (
            enhance_mission,
        )

        mission = {
            "title": "타이어 교체 후보 조사",
            "summary": "창원시청 주변에서 타이어 교체할 곳을 결정한다.",
            "category": "자동차",
            "subcategories": ["타이어"],
            "intent": "비교",
            "response_mode": "research",
            "search_mode": "area_discovery",
            "location": "창원시청",
            "subject": "타이어 교체",
            "constraints": [],
            "comparison": "접근성과 실제 작업 가능성",
            "required_facts": [
                "후보 업체",
                "거리",
                "현재 작업 가능 여부",
            ],
            "needs_fresh_data": True,
            "may_need_phone_call": True,
            "missing_information": [],
            "clarification_questions": [],
            "ready_to_research": True,
            "search_terms": ["타이어 교체"],
        }

        result = enhance_mission(
            mission,
            "창원시청 주변에 타이어 교체할 곳 알아봐",
        )

        self.assertEqual(
            result["category"],
            "자동차",
        )
        self.assertEqual(
            result["search_terms"],
            ["타이어 교체"],
        )
        self.assertTrue(
            result["user_goal"],
        )
        self.assertEqual(
            result["expected_answer"]["type"],
            "comparison",
        )
        self.assertIn(
            "거리",
            result["expected_answer"]["must_include"],
        )
        self.assertTrue(
            result["evidence_needed"],
        )
        self.assertTrue(
            result["research_plan"],
        )
        self.assertEqual(
            result["brain_version"],
            "goal-first-v1",
        )

    def test_reference_point_location_is_preserved_as_reference_point(
        self,
    ):
        from api.services.intent_brain_service import (
            enhance_mission,
        )

        result = enhance_mission(
            {
                "summary": "기준 장소 주변 후보 조사",
                "intent": "조사",
                "response_mode": "research",
                "location": "창원시청",
                "location_context": {
                    "value": "창원시청",
                    "type": "reference_point",
                    "radius_hint_km": 3,
                },
                "required_facts": ["주변 후보"],
                "may_need_phone_call": False,
            },
            "창원시청 주변에 알아봐",
        )

        self.assertEqual(
            result["location_context"]["type"],
            "reference_point",
        )
        self.assertEqual(
            result["location_context"]["value"],
            "창원시청",
        )
        self.assertEqual(
            result["location_context"]["radius_hint_km"],
            3.0,
        )

    def test_non_place_goal_can_plan_without_place_search(
        self,
    ):
        from api.services.intent_brain_service import (
            enhance_mission,
        )

        result = enhance_mission(
            {
                "summary": "계약서에서 위험 조항을 설명한다.",
                "intent": "조사",
                "response_mode": "research",
                "subject": "계약서 위험조항",
                "required_facts": [
                    "불리한 조항",
                    "확인할 사항",
                ],
                "may_need_phone_call": False,
                "research_plan": [
                    {
                        "step": 1,
                        "goal": "첨부 계약서 내용을 확인한다.",
                        "tool": "image",
                        "when": "계약서 사진 또는 파일이 있을 때",
                    },
                    {
                        "step": 2,
                        "goal": "위험조항의 의미를 분석한다.",
                        "tool": "direct_reasoning",
                        "when": "문서 내용이 추출된 뒤",
                    },
                ],
            },
            "이 계약서 괜찮은지 봐줘",
        )

        tools_used = [
            step["tool"]
            for step in result["research_plan"]
        ]

        self.assertEqual(
            tools_used,
            ["image", "direct_reasoning"],
        )
        self.assertNotIn(
            "place_search",
            tools_used,
        )
