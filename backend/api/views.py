import json
import logging
from time import monotonic
from uuid import uuid4

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


def _request_naver_client_id(request):
    return str(
        request.headers.get("X-Naver-Client-Id", "")
    ).strip()


def _request_naver_client_secret(request):
    return str(
        request.headers.get("X-Naver-Client-Secret", "")
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
def onboarding_schemas(request):
    from .services.profile_schema_service import (
        signup_schema_catalog,
    )

    return Response(
        {
            "ok": True,
            **signup_schema_catalog(),
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
    from .services.mission_service import (
        MISSION_MODEL, MISSION_TIMEOUT_SECONDS, create_mission,
    )

    started = monotonic()
    diagnostics = {
        "request_id": uuid4().hex,
        "stage": "mission_create",
        "model": MISSION_MODEL,
        "timeout_seconds": MISSION_TIMEOUT_SECONDS,
        "retries": 0,
    }

    def finish(payload, http_status, exc=None):
        diagnostics["server_elapsed_ms"] = round((monotonic() - started) * 1000)
        diagnostics["http_status"] = http_status
        if exc is not None:
            diagnostics["exception_type"] = type(exc).__name__
            upstream_status = getattr(exc, "status_code", None)
            if isinstance(upstream_status, int):
                diagnostics["upstream_http_status"] = upstream_status
            request_id = getattr(exc, "request_id", None)
            if isinstance(request_id, str):
                diagnostics["upstream_request_id"] = request_id[:200]
        # Never log request text, API keys, response bodies or raw exceptions.
        logging.getLogger(__name__).warning(
            "mission_diagnostic %s", json.dumps(diagnostics, ensure_ascii=False)
        )
        return Response(
            {**payload, "diagnostics": diagnostics},
            status=http_status,
            headers={"X-Request-ID": diagnostics["request_id"]},
        )

    try:
        user_request = str(request.data.get("request", "")).strip()
        mission = create_mission(
            user_request, _request_api_key(request), diagnostics=diagnostics,
        )
        diagnostics["stage"] = "complete"
        return finish({"ok": True, "mission": mission}, 200)
    except Exception as exc:
        error_name = type(exc).__name__
        if isinstance(exc, ValueError):
            http_status = 400
            message = str(exc)
        elif error_name in {"AuthenticationError", "PermissionDeniedError"}:
            http_status = 401
            message = "OpenAI API Key 인증에 실패했습니다. MY의 API Key를 다시 확인해주세요."
        elif error_name in {"APITimeoutError", "TimeoutError"}:
            http_status = 504
            message = "AI 요청 이해 중 응답 대기시간을 초과했습니다. 자동 재시도는 하지 않았습니다."
        elif error_name in {"APIConnectionError", "ConnectError"}:
            http_status = 502
            message = "AI 요청 이해 서버와 연결하지 못했습니다. 자동 재시도는 하지 않았습니다."
        else:
            http_status = 500
            message = "Mission 생성 중 오류가 발생했습니다. 아래 진단 정보를 확인해주세요."
        return finish({"ok": False, "message": message}, http_status, exc)


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


@api_view(["GET"])
def live_telephony_status_view(request):
    from .services.live_service import (
        live_telephony_status,
    )

    return Response(
        {
            "ok": True,
            **live_telephony_status(),
        }
    )


@api_view(["POST"])
def live_outbound_call(request):
    from .services.live_service import (
        LiveConfigurationError,
        create_outbound_live_call,
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

    try:
        result = create_outbound_live_call(
            str(
                request.data.get(
                    "phone_number",
                    "",
                )
            ).strip(),
            api_key=api_key,
            purpose=str(
                request.data.get(
                    "purpose",
                    "",
                )
            ).strip(),
            business_name=str(
                request.data.get(
                    "business_name",
                    "",
                )
            ).strip(),
            requested_time=str(
                request.data.get(
                    "requested_time",
                    "",
                )
            ).strip(),
            reservation_name=str(
                request.data.get(
                    "reservation_name",
                    "",
                )
            ).strip(),
            notes=str(
                request.data.get(
                    "notes",
                    "",
                )
            ).strip(),
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
        )

        return Response(
            {
                "ok": True,
                **result,
                "message": (
                    "GPT-Live 실전화 세션을 시작했습니다."
                ),
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
                "message": (
                    "GPT-Live 실전화 시작 중 서버 오류가 발생했습니다."
                ),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["POST"])
def research_enrich(request):
    """Second phase: enrich only the Kakao-verified card candidates."""
    from .services.research_service import enrich_place_businesses
    from .services.business_matching_service import match_businesses

    mission = request.data.get("mission")
    businesses = request.data.get("businesses")

    if not isinstance(mission, dict):
        return Response(
            {"ok": False, "message": "검색 조건이 필요합니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if (
        not isinstance(businesses, list)
        or not 0 < len(businesses) <= 10
        or any(
            not isinstance(item, dict)
            or not str(item.get("name") or "").strip()
            or not str(item.get("address") or "").strip()
            for item in businesses
        )
    ):
        return Response(
            {"ok": False, "message": "검증된 업체 1~10곳이 필요합니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _request_api_key(request):
        return Response(
            {"ok": False, "message": "OpenAI API Key가 필요합니다."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    result = enrich_place_businesses(
        businesses,
        mission,
        naver_client_id=_request_naver_client_id(request),
        naver_client_secret=_request_naver_client_secret(request),
        openai_api_key=_request_api_key(request),
        gpt_direct=True,
    )
    matching = match_businesses(
        mission,
        result,
    )
    display_result = matching["display_businesses"]
    counts = {
        "hours": 0,
        "parking": 0,
        "prices": 0,
        "photos": 0,
        "image_candidates": 0,
    }
    for item in display_result:
        naver = item.get("naver") or {}
        if not isinstance(naver, dict):
            naver = {}
        counts["hours"] += bool(naver.get("opening_hours"))
        counts["parking"] += isinstance(
            naver.get("parking_available"), bool
        )
        counts["prices"] += bool(naver.get("prices"))
        counts["photos"] += bool(item.get("image_url"))
        openai_web = item.get("openai_web") or {}
        if isinstance(openai_web, dict):
            counts["image_candidates"] += int(
                openai_web.get("image_result_count") or 0
            )

    return Response(
        {
            "ok": True,
            "businesses": display_result,
            "matching": matching,
            "detail_status": "complete",
            "coverage": counts,
        }
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
            naver_client_id=_request_naver_client_id(request),
            naver_client_secret=_request_naver_client_secret(request),
            openai_api_key=_request_api_key(request),
            quick_cards=request.data.get("quick_cards") is True,
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
def business_experience_create(request):
    from .services.business_graph_service import add_business_experience

    try:
        result = add_business_experience(
            business_id=request.data.get("business_id"),
            provider_place_id=request.data.get("provider_place_id"),
            raw_text=request.data.get("text"),
            rating=request.data.get("rating"),
            verified_visit=request.data.get("verified_visit") is True,
        )
        return Response({"ok": True, **result})
    except ValueError as exc:
        return Response(
            {"ok": False, "message": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
def business_experience_list(request):
    from .services.business_graph_service import list_business_experiences

    business_id = request.query_params.get("business_id")
    if not business_id:
        return Response(
            {"ok": False, "message": "business_id가 필요합니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = list_business_experiences(
            business_id,
            limit=request.query_params.get("limit", 20),
        )
        return Response({"ok": True, **result})
    except (TypeError, ValueError) as exc:
        return Response(
            {"ok": False, "message": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
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
def training_core_curriculum(request):
    from .services.training_service import (
        CORE_CURRICULUM,
        run_core_curriculum_diagnostics,
    )

    try:
        runs = run_core_curriculum_diagnostics()
        passed = sum(
            1
            for run in runs
            if run.score >= 100
        )

        return Response(
            {
                "ok": True,
                "trained": len(runs),
                "passed": passed,
                "failed": len(runs) - passed,
                "historical_count": sum(
                    1
                    for item in CORE_CURRICULUM
                    if item["group"] == "historical_failure"
                ),
                "future_complex_count": sum(
                    1
                    for item in CORE_CURRICULUM
                    if item["group"] == "future_complex"
                ),
                "observed_failure_count": sum(
                    1
                    for item in CORE_CURRICULUM
                    if item["group"] == "observed_failure"
                ),
                "runs": [
                    {
                        "id": run.id,
                        "scenario": (
                            run.scenario.title
                            if run.scenario
                            else None
                        ),
                        "score": run.score,
                        "mistakes": run.mistakes,
                    }
                    for run in runs
                ],
            }
        )
    except Exception as exc:
        return Response(
            {
                "ok": False,
                "message": (
                    "핵심 훈련 커리큘럼 실행 중 오류가 발생했습니다: "
                    f"{exc}"
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
def training_live_feedback(request):
    from .services.live_trainer_service import (
        analyze_and_learn_trainer_feedback,
        record_correct_feedback,
    )

    verdict = str(
        request.data.get("verdict", "")
    ).strip().lower()
    category = request.data.get("category", "")
    request_text = request.data.get("request_text", "")
    assistant_response = request.data.get(
        "assistant_response",
        "",
    )
    context = request.data.get("context")

    try:
        if verdict == "correct":
            result = record_correct_feedback(
                category=category,
                request_text=request_text,
                assistant_response=assistant_response,
                context=context,
            )
        elif verdict == "wrong":
            result = analyze_and_learn_trainer_feedback(
                api_key=_request_api_key(request),
                category=category,
                request_text=request_text,
                assistant_response=assistant_response,
                trainer_note=request.data.get("trainer_note", ""),
                expected_behavior=request.data.get(
                    "expected_behavior",
                    "",
                ),
                context=context,
                actor_role=request.data.get(
                    "actor_role",
                    "trainer",
                ),
            )
        else:
            raise ValueError("verdict는 correct 또는 wrong이어야 합니다.")

        return Response({"ok": True, **result})
    except ValueError as exc:
        return Response(
            {"ok": False, "message": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        return Response(
            {
                "ok": False,
                "message": (
                    "실시간 훈련 분석 중 오류가 발생했습니다: "
                    f"{type(exc).__name__}"
                ),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["GET"])
def training_lab_cases(request):
    from .services.lab_service import list_lab_cases

    return Response(
        {
            "ok": True,
            **list_lab_cases(
                status=request.query_params.get("status"),
                limit=request.query_params.get("limit", 50),
            ),
        }
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
