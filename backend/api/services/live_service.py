import logging
import os
import re

import httpx

from .openai_service import get_api_key
from .training_service import active_rules_text


OPENAI_LIVE_SESSIONS_URL = "https://api.openai.com/v1/live/sessions"

SIP_ENV = {
    "provider_url": "ARABA_SIP_PROVIDER_URL",
    "username": "ARABA_SIP_USERNAME",
    "password": "ARABA_SIP_PASSWORD",
    "caller_number": "ARABA_SIP_CALLER_NUMBER",
}

logger = logging.getLogger(__name__)

LIVE_SYSTEM_PROMPT = """
당신은 ARABA(알아봐)의 실시간 한국어 음성 인터페이스다.

핵심 원칙:
- 당신은 ARABA의 귀와 입이다. 실질적인 판단을 하는 두뇌는 GPT Core 하나뿐이다.
- 사용자가 말하는 동안에는 먼저 끼어들지 않는다. 짧은 침묵, "음", "어", "그거", "이거는" 같은 머뭇거림은 발화 종료로 간주하지 말고 조용히 기다린다.
- 사용자의 원시 음성 발화에 스스로 맞장구나 답변을 생성하지 않는다. 앱이 GPT Core의 확정 결과나 질문을 commentary로 전달했을 때만 그것을 자연스럽게 말한다.
- 정보, 판단, 추천, 비교, 진단, 최신 사실, 가격, 재고, 영업 여부, 예약 가능 여부,
  업체 사실, 검색 결과처럼 사용자의 의사결정에 영향을 주는 내용은 직접 결론내리지 않는다.
- 그런 요청에는 "알겠어요. 확인해볼게요.", "조건을 정리해서 보고 있어요."처럼
  사실을 포함하지 않는 짧은 완충 응답만 한다.
- GPT Core가 확정한 결과가 전달되면 그 내용을 자연스럽고 간결하게 사용자에게 말한다.
- 앱에서 전달된 결과 브리핑에는 없는 지명, 동네명, 상호명, 숫자, 영업정보를 절대 보충하거나 추측하지 않는다.
- 결과 브리핑에 업체명이 들어 있지 않으면 업체명을 새로 만들어 말하지 않는다. 지역명이 들어 있으면 그 지역명만 그대로 사용한다.
- 장소검색 완료 브리핑은 앱이 전달한 검증 문장 범위 안에서만 말하고, 카드에 없는 후보를 음성으로 추가하지 않는다.
- 사용자가 "진행 중이야?", "아직 보고 있어?"처럼 절차 상태를 묻는 경우
  확인되지 않은 진행 수치나 결과를 만들지 말고 "확인 중이에요." 정도로만 답한다.
- "찾았다", "몇 곳 확인했다", "여기가 가장 싸다", "예약 가능하다" 같은 표현은
  GPT Core가 실제 결과를 전달한 경우에만 사용한다.
- 사용자가 단순 인사, 감사, 짧은 맞장구처럼 사실 판단이 필요 없는 말을 하면
  자연스럽게 짧게 응답할 수 있다.
- 사용자가 이미 말한 조건을 반복해서 묻지 않는다.
- 항상 자연스러운 한국어 존댓말을 사용하고 전화 대화처럼 간결하게 말한다.
""".strip()


class LiveConfigurationError(ValueError):
    pass


def _env(name):
    return str(os.getenv(name, "")).strip()


def normalize_live_phone_number(value):
    raw = str(value or "").strip()
    compact = re.sub(r"[\s\-().]", "", raw)

    if compact.startswith("+"):
        normalized = compact
    elif compact.startswith("82"):
        normalized = "+" + compact
    elif compact.startswith("0"):
        digits = re.sub(r"\D", "", compact)
        if not 9 <= len(digits) <= 11:
            raise LiveConfigurationError(
                "전화번호 형식이 올바르지 않습니다."
            )
        normalized = "+82" + digits[1:]
    else:
        raise LiveConfigurationError(
            "전화번호는 국내 번호 또는 E.164 국제번호 형식으로 입력해주세요."
        )

    if not re.fullmatch(r"\+[1-9]\d{7,14}", normalized):
        raise LiveConfigurationError(
            "전화번호 형식이 올바르지 않습니다."
        )

    return normalized


def live_telephony_status():
    values = {
        key: _env(env_name)
        for key, env_name in SIP_ENV.items()
    }
    missing = [
        SIP_ENV[key]
        for key, value in values.items()
        if not value
    ]

    provider_url = values["provider_url"]
    provider_valid = (
        not provider_url
        or provider_url.startswith("sips:")
    )

    return {
        "ready": not missing and provider_valid,
        "transport": "sip",
        "model": "gpt-live-1",
        "missing": missing,
        "provider_url_valid": provider_valid,
        "caller_number_configured": bool(
            values["caller_number"]
        ),
    }


def _live_voice(
    voice_gender,
):
    gender = str(
        voice_gender or "female"
    ).strip().lower()
    return "cedar" if gender == "male" else "marin"


def _live_speed_instruction(
    voice_speed,
):
    speed = str(
        voice_speed or "medium"
    ).strip().lower()

    return {
        "slow": "평소보다 조금 느리고 또렷하게 말한다.",
        "fast": "핵심이 잘 들리는 범위에서 조금 빠르게 말한다.",
    }.get(
        speed,
        "자연스러운 보통 속도로 말한다.",
    )


def _outbound_call_instructions(
    *,
    purpose,
    business_name="",
    requested_time="",
    reservation_name="",
    notes="",
    voice_speed="medium",
):
    task = str(purpose or "").strip()
    if not task:
        raise LiveConfigurationError(
            "전화로 처리할 목적이 필요합니다."
        )

    facts = [
        f"통화 목적: {task}",
    ]

    business = str(business_name or "").strip()
    if business:
        facts.append(f"상대 업체명: {business}")

    requested = str(requested_time or "").strip()
    if requested:
        facts.append(f"희망 일정: {requested}")

    name = str(reservation_name or "").strip()
    if name:
        facts.append(f"예약자 이름: {name}")

    extra = str(notes or "").strip()
    if extra:
        facts.append(f"추가 조건: {extra}")

    return (
        "당신은 ARABA(알아봐)의 한국어 전화 예약·문의 AI 비서다.\n"
        "실제 업체에 전화를 걸어 아래 사용자의 요청을 처리한다.\n\n"
        + "\n".join(facts)
        + "\n\n"
        "통화 규칙:\n"
        "1. 처음에는 짧게 인사하고, 사용자를 대신해 예약 또는 문의하는 "
        "AI 비서임을 자연스럽게 밝힌다. 특정 플랫폼이나 통신사 이름을 말하지 않는다.\n"
        "2. 상대방에게 필요한 내용만 한 번에 하나씩 묻고 장황하게 설명하지 않는다.\n"
        "3. 상대가 이미 답한 사항은 다시 묻지 않는다.\n"
        "4. 가격, 시간, 재고, 예약 가능 여부를 추측하거나 만들어내지 않는다.\n"
        "5. 희망 조건이 불가능하면 가장 가까운 대안을 짧게 확인한다.\n"
        "6. 예약자 이름 등 제공된 정보만 사용하고, 없는 개인정보를 만들어내지 않는다.\n"
        "7. 예약이나 문의 결과를 마지막에 한 문장으로 다시 확인한 뒤 정중히 통화를 마친다.\n"
        "8. 상대가 통화를 원하지 않거나 잘못 걸린 번호라고 하면 즉시 사과하고 종료한다.\n"
        "9. 항상 자연스러운 한국어 존댓말을 사용한다.\n"
        "10. "
        + _live_speed_instruction(voice_speed)
    )


def create_outbound_live_call(
    phone_number,
    *,
    api_key=None,
    purpose,
    business_name="",
    requested_time="",
    reservation_name="",
    notes="",
    voice_gender="female",
    voice_speed="medium",
):
    key = get_api_key(api_key)
    if not key:
        raise LiveConfigurationError(
            "OpenAI API Key가 설정되지 않았습니다."
        )

    status = live_telephony_status()
    if not status["ready"]:
        if not status["provider_url_valid"]:
            raise LiveConfigurationError(
                "SIP provider URL은 sips: 형식이어야 합니다."
            )

        missing = ", ".join(status["missing"])
        raise LiveConfigurationError(
            "GPT-Live 전화용 SIP 설정이 아직 필요합니다: "
            + missing
        )

    destination = normalize_live_phone_number(
        phone_number
    )
    caller_number = normalize_live_phone_number(
        _env(SIP_ENV["caller_number"])
    )
    provider_url = _env(SIP_ENV["provider_url"])

    payload = {
        "session": {
            "model": "gpt-live-1",
            "instructions": _outbound_call_instructions(
                purpose=purpose,
                business_name=business_name,
                requested_time=requested_time,
                reservation_name=reservation_name,
                notes=notes,
                voice_speed=voice_speed,
            ),
            "audio": {
                "output": {
                    "voice": _live_voice(
                        voice_gender
                    ),
                },
            },
            "delegation": {
                "type": "responses",
                "responses": {
                    "model": "gpt-6-luna",
                    "instructions": (
                        "전화 통화의 목적 달성에 필요한 최소한의 판단만 한다. "
                        "확인되지 않은 사실을 만들지 말고, "
                        "상대방이 제공한 정보와 사용자가 준 조건만 이용한다."
                    ),
                    "max_output_tokens": 300,
                },
            },
            "store": False,
        },
        "transport": {
            "type": "sip",
            "destination": destination,
            "trunk": {
                "provider_url": provider_url,
                "auth": {
                    "type": "digest",
                    "username": _env(
                        SIP_ENV["username"]
                    ),
                    "password": _env(
                        SIP_ENV["password"]
                    ),
                },
                "caller_number": caller_number,
            },
        },
    }

    try:
        response = httpx.post(
            OPENAI_LIVE_SESSIONS_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45.0,
        )
    except httpx.HTTPError as exc:
        raise LiveConfigurationError(
            "GPT-Live 전화 서버에 연결하지 못했습니다."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        try:
            error_data = response.json()
        except ValueError:
            error_data = {}

        error = error_data.get("error")
        if isinstance(error, dict):
            error_code = str(
                error.get("code") or ""
            ).strip()
            message = str(
                error.get("message") or ""
            ).strip()
        else:
            error_code = str(
                error_data.get("code") or ""
            ).strip()
            message = str(
                error_data.get("message") or ""
            ).strip()

        if (
            response.status_code == 403
            and error_code == "outbound_sip_not_enabled"
        ):
            raise LiveConfigurationError(
                "현재 OpenAI 조직에서 GPT-Live outbound SIP가 활성화되지 않았습니다."
            )

        raise LiveConfigurationError(
            "GPT-Live 전화 세션 생성에 실패했습니다."
            + (f" {message}" if message else "")
        )

    data = response.json()
    session_id = str(
        data.get("session", {}).get("id", "")
    ).strip()

    if not session_id:
        raise LiveConfigurationError(
            "GPT-Live 전화 세션 ID를 받지 못했습니다."
        )

    return {
        "session_id": session_id,
        "destination": destination,
        "caller_number": caller_number,
        "transport": "sip",
        "model": "gpt-live-1",
        "status": "initializing",
    }


def create_live_session(
    offer_sdp,
    api_key=None,
    *,
    voice_gender="female",
    voice_speed="medium",
):
    offer_sdp = "" if offer_sdp is None else str(offer_sdp)

    if not offer_sdp.strip():
        raise LiveConfigurationError(
            "GPT-Live 연결용 SDP가 없습니다."
        )

    required_sdp_parts = (
        "v=0",
        "m=audio",
        "a=ice-ufrag:",
        "a=ice-pwd:",
    )

    if any(part not in offer_sdp for part in required_sdp_parts):
        raise LiveConfigurationError(
            "GPT-Live 연결용 SDP 형식이 올바르지 않습니다."
        )

    logger.info(
        "GPT-Live SDP offer: length=%s, starts_v0=%s, has_audio=%s",
        len(offer_sdp),
        offer_sdp.startswith("v=0"),
        "m=audio" in offer_sdp,
    )

    key = get_api_key(api_key)

    if not key:
        raise LiveConfigurationError(
            "OpenAI API Key가 설정되지 않았습니다."
        )

    voice = _live_voice(
        voice_gender
    )
    speed_instruction = _live_speed_instruction(
        voice_speed
    )

    learned_rules = active_rules_text(
        limit=30,
    )
    instructions = (
        LIVE_SYSTEM_PROMPT
        + "\n- 음성속도 지침: "
        + speed_instruction
    )

    if learned_rules:
        instructions += (
            "\n\n누적된 재발방지 학습규칙:\n"
            + learned_rules
        )

    instructions += (
        "\n\n최우선 음성 출력 규칙:\n"
        "- 앱의 commentary로 전달된 검색 결과는 그 문장에 있는 사실만 말한다.\n"
        "- commentary에 없는 지명·상호·후보·숫자를 절대 생성하지 않는다.\n"
        "- 장소검색 중에는 스스로 검색 결과를 말하지 않는다."
    )

    payload = {
        "session": {
            "model": "gpt-live-1",
            "instructions": instructions,
            "audio": {
                "output": {
                    "voice": voice,
                },
            },
            "store": False,
        },
        "transport": {
            "type": "webrtc",
            "sdp": offer_sdp,
        },
    }

    try:
        response = httpx.post(
            OPENAI_LIVE_SESSIONS_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45.0,
        )
    except httpx.HTTPError as exc:
        raise LiveConfigurationError(
            "OpenAI GPT-Live 서버에 연결하지 못했습니다."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        try:
            error_data = response.json()
            message = (
                error_data.get("error", {}).get("message")
                or error_data.get("message")
            )
        except ValueError:
            message = None

        raise LiveConfigurationError(
            "GPT-Live 세션 생성에 실패했습니다."
            + (f" {message}" if message else "")
        )

    data = response.json()
    session_id = str(
        data.get("session", {}).get("id", "")
    ).strip()
    answer_sdp_value = data.get("transport", {}).get("sdp", "")
    answer_sdp = (
        ""
        if answer_sdp_value is None
        else str(answer_sdp_value)
    )

    if not session_id or not answer_sdp.strip():
        raise LiveConfigurationError(
            "GPT-Live 세션 응답이 올바르지 않습니다."
        )

    return {
        "session_id": session_id,
        "sdp": answer_sdp,
        "model": "gpt-live-1",
        "routing": "gpt_core",
    }
