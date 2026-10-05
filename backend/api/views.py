from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .services.openai_service import (
    get_openai_status,
    test_openai_connection,
)


def _request_api_key(request):
    return str(
        request.headers.get("X-OpenAI-API-Key", "")
    ).strip()


@api_view(["GET"])
def health(request):
    return Response(
        {
            "ok": True,
            "service": "ARABA API",
        }
    )


@api_view(["GET"])
def openai_status(request):
    return Response(
        {
            "ok": True,
            **get_openai_status(
                _request_api_key(request)
            ),
        }
    )


@api_view(["POST"])
def openai_save(request):
    return Response(
        {
            "ok": False,
            "message": (
                "API Key는 서버에 저장하지 않습니다. "
                "최신 ARABA 앱의 MY 화면에서 기기에 저장하세요."
            ),
        },
        status=status.HTTP_410_GONE,
    )


@api_view(["POST"])
def openai_test(request):
    try:
        result = test_openai_connection(
            _request_api_key(request)
        )

        return Response(
            {
                "ok": True,
                **result,
                "message": "OpenAI 연결에 성공했습니다.",
            }
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "connected": False,
                "message": f"OpenAI 연결 실패: {exc}",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
def mission_create(request):
    from .services.mission_service import create_mission

    try:
        user_request = str(
            request.data.get("request", "")
        ).strip()

        mission = create_mission(
            user_request,
            _request_api_key(request),
        )

        return Response(
            {
                "ok": True,
                "mission": mission,
            }
        )

    except ValueError as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "message": (
                    "Mission 생성 중 오류가 발생했습니다: "
                    f"{exc}"
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
def notify_update(request):
    from .services.update_notification_service import (
        send_update_notification,
        verify_github_actions_token,
    )

    authorization = str(
        request.headers.get("Authorization", "")
    ).strip()

    if not authorization.startswith("Bearer "):
        return Response(
            {
                "ok": False,
                "message": "GitHub OIDC 인증이 필요합니다.",
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    token = authorization.removeprefix("Bearer ").strip()

    try:
        claims = verify_github_actions_token(token)
        message_id = send_update_notification()

        return Response(
            {
                "ok": True,
                "message_id": message_id,
                "repository": claims.get("repository"),
                "ref": claims.get("ref"),
            }
        )
    except ValueError as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    except Exception as exc:
        return Response(
            {
                "ok": False,
                "message": (
                    "업데이트 알림 전송 중 오류가 발생했습니다: "
                    f"{exc}"
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



@api_view(["POST"])
def live_session_create(request):
    from .services.live_service import (
        LiveConfigurationError,
        create_live_session,
    )

    api_key = _request_api_key(request)

    if not api_key:
        return Response(
            {
                "ok": False,
                "message": "OpenAI API Key가 필요합니다.",
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    offer_sdp_value = request.data.get("sdp", "")
    offer_sdp = (
        ""
        if offer_sdp_value is None
        else str(offer_sdp_value)
    )

    try:
        result = create_live_session(
            offer_sdp,
            api_key,
        )

        return Response(
            {
                "ok": True,
                **result,
            }
        )
    except LiveConfigurationError as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        return Response(
            {
                "ok": False,
                "message": "GPT-Live 연결 중 서버 오류가 발생했습니다.",
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["POST"])
def notification_register(request):
    from .services.update_notification_service import (
        subscribe_device_to_updates,
    )

    token = str(request.data.get("token", "")).strip()

    try:
        result = subscribe_device_to_updates(token)

        return Response(
            {
                "ok": True,
                **result,
            }
        )
    except ValueError as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        return Response(
            {
                "ok": False,
                "message": (
                    "푸시 알림 등록 중 오류가 발생했습니다: "
                    f"{exc}"
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



@api_view(["GET"])
def voice_status(request):
    from .services.voice_call_service import (
        voice_configuration_status,
    )

    return Response(
        {
            "ok": True,
            **voice_configuration_status(),
        }
    )


@api_view(["POST"])
def voice_test_call(request):
    from .services.voice_call_service import (
        VoiceConfigurationError,
        start_test_call,
    )

    if not _request_api_key(request):
        return Response(
            {
                "ok": False,
                "message": "OpenAI API Key가 필요합니다.",
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    account_sid = str(
        request.headers.get(
            "X-Twilio-Account-SID",
            "",
        )
    ).strip()
    auth_token = str(
        request.headers.get(
            "X-Twilio-Auth-Token",
            "",
        )
    ).strip()
    from_number = str(
        request.headers.get(
            "X-Twilio-From-Number",
            "",
        )
    ).strip()
    phone_number = str(
        request.data.get("phone_number", "")
    ).strip()

    try:
        result = start_test_call(
            phone_number,
            account_sid=account_sid,
            auth_token=auth_token,
            from_number=from_number or None,
            api_key=_request_api_key(request),
        )

        return Response(
            {
                "ok": True,
                **result,
                "message": "AI 테스트 전화를 시작했습니다.",
            }
        )
    except (ValueError, VoiceConfigurationError) as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        return Response(
            {
                "ok": False,
                "message": (
                    "AI 테스트 전화 발신에 실패했습니다: "
                    f"{exc}"
                ),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["POST"])
def voice_answer(request):
    from .services.voice_call_service import (
        build_answer_twiml,
    )

    session = str(
        request.query_params.get("session", "")
    ).strip()

    try:
        twiml = build_answer_twiml(session)
    except Exception:
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Response>'
            '<Say language="ko-KR">'
            '음성통화 세션을 시작할 수 없습니다.'
            '</Say><Hangup/>'
            '</Response>'
        )

    return HttpResponse(
        twiml,
        content_type="text/xml; charset=utf-8",
    )


@api_view(["POST"])
def voice_respond(request):
    from .services.voice_call_service import (
        build_response_twiml,
    )

    session = str(
        request.query_params.get("session", "")
    ).strip()
    previous_response_id = str(
        request.query_params.get(
            "previous_response_id",
            "",
        )
    ).strip() or None
    speech = str(
        request.data.get("SpeechResult", "")
    ).strip()

    try:
        twiml = build_response_twiml(
            session,
            speech,
            previous_response_id=previous_response_id,
        )
    except Exception:
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Response>'
            '<Say language="ko-KR">'
            'AI 응답 처리 중 문제가 생겨 테스트 통화를 종료합니다.'
            '</Say><Hangup/>'
            '</Response>'
        )

    return HttpResponse(
        twiml,
        content_type="text/xml; charset=utf-8",
    )
