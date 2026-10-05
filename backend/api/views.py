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


def _request_kakao_rest_api_key(request):
    return str(
        request.headers.get("X-Kakao-REST-API-Key", "")
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
        voice_gender = request.data.get(
            "voice_gender"
        )
        voice_speed = request.data.get(
            "voice_speed"
        )

        if (
            voice_gender is None
            and voice_speed is None
        ):
            result = create_live_session(
                offer_sdp,
                api_key,
            )
        else:
            result = create_live_session(
                offer_sdp,
                api_key,
                voice_gender=str(
                    voice_gender or "female"
                ),
                voice_speed=str(
                    voice_speed or "medium"
                ),
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
def research_search(request):
    from .services.research_service import (
        ResearchConfigurationError,
        ResearchProviderError,
        search_real_businesses,
    )

    mission = request.data.get("mission")

    if not isinstance(mission, dict):
        return Response(
            {
                "ok": False,
                "message": "조사 Mission 정보가 필요합니다.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = search_real_businesses(
            mission,
            api_key=_request_kakao_rest_api_key(request),
        )
        return Response(
            {
                "ok": True,
                **result,
            }
        )
    except ResearchConfigurationError as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ResearchProviderError as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["POST"])
def mock_call_compare(request):
    from .services.mock_call_service import simulate_mock_calls
    from .services.research_record_service import save_research_record

    mission = request.data.get("mission")
    businesses = request.data.get("businesses")
    origin = request.data.get("origin")

    try:
        result = simulate_mock_calls(
            mission,
            businesses,
            origin=origin,
        )
        record = save_research_record(
            mission,
            result,
        )
        return Response(
            {
                "ok": True,
                "record_id": record.id,
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


@api_view(["GET"])
def research_history(request):
    from .services.research_record_service import (
        list_research_records_grouped,
    )

    try:
        limit = int(
            request.query_params.get("limit", "50")
        )
    except ValueError:
        limit = 50

    return Response(
        {
            "ok": True,
            **list_research_records_grouped(
                limit=limit,
            ),
        }
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
    caller_id_number = str(
        request.headers.get(
            "X-Twilio-Caller-ID",
            "",
        )
    ).strip()
    phone_number = str(
        request.data.get("phone_number", "")
    ).strip()

    try:
        extra_voice_fields = any(
            key in request.data
            for key in (
                "voice_gender",
                "voice_speed",
                "training_mode",
                "training_category",
            )
        )

        if not extra_voice_fields:
            result = start_test_call(
                phone_number,
                account_sid=account_sid,
                auth_token=auth_token,
                from_number=from_number or None,
                caller_id_number=caller_id_number or None,
                api_key=_request_api_key(request),
            )
        else:
            result = start_test_call(
                phone_number,
                account_sid=account_sid,
                auth_token=auth_token,
                from_number=from_number or None,
                caller_id_number=caller_id_number or None,
                api_key=_request_api_key(request),
                voice_gender=str(
                    request.data.get(
                        "voice_gender",
                        "female",
                    )
                ),
                voice_speed=str(
                    request.data.get(
                        "voice_speed",
                        "medium",
                    )
                ),
                training_mode=bool(
                    request.data.get(
                        "training_mode",
                        False,
                    )
                ),
                training_category=str(
                    request.data.get(
                        "training_category",
                        "",
                    )
                ),
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


@api_view(["POST"])
def image_analyze(request):
    from .services.image_analysis_service import (
        analyze_image_bytes,
    )

    image = request.FILES.get("image")

    if image is None:
        return Response(
            {
                "ok": False,
                "message": "판독할 사진을 첨부해주세요.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = analyze_image_bytes(
            image.read(),
            mime_type=(
                str(
                    request.data.get(
                        "mime_type",
                        "",
                    )
                ).strip()
                or getattr(
                    image,
                    "content_type",
                    None,
                )
                or "image/jpeg"
            ),
            context=str(
                request.data.get("context", "")
            ).strip(),
            api_key=_request_api_key(request),
        )

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
                    "사진 판독 중 오류가 발생했습니다: "
                    f"{exc}"
                ),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["GET"])
def training_status_view(request):
    from .services.training_service import (
        training_status,
    )

    return Response(
        {
            "ok": True,
            **training_status(),
        }
    )


@api_view(["POST"])
def training_generate(request):
    from .services.training_service import (
        generate_training_scenarios,
    )

    try:
        scenarios = generate_training_scenarios(
            category=request.data.get("category"),
            limit=request.data.get("limit", 10),
        )

        return Response(
            {
                "ok": True,
                "created": len(scenarios),
                "scenario_ids": [
                    scenario.id
                    for scenario in scenarios
                ],
            }
        )
    except (ValueError, TypeError) as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
def training_run_auto(request):
    from .services.training_service import (
        run_auto_training,
    )

    try:
        runs = run_auto_training(
            api_key=_request_api_key(request),
            limit=request.data.get("limit", 4),
            category=request.data.get("category"),
        )

        return Response(
            {
                "ok": True,
                "trained": len(runs),
                "scores": [
                    run.score
                    for run in runs
                ],
            }
        )
    except (ValueError, TypeError) as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
def training_feedback(request):
    from .services.training_service import (
        save_training_rule,
    )

    try:
        rule = save_training_rule(
            category=request.data.get(
                "category",
                "",
            ),
            trigger=request.data.get(
                "trigger",
                "",
            ),
            instruction=request.data.get(
                "instruction",
                "",
            ),
            example=request.data.get(
                "example",
                "",
            ),
            source="admin",
            confidence=1.0,
        )

        return Response(
            {
                "ok": True,
                "rule_id": rule.id,
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
