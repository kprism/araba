import logging

import httpx

from .openai_service import get_api_key


OPENAI_LIVE_SESSIONS_URL = "https://api.openai.com/v1/live/sessions"

logger = logging.getLogger(__name__)

LIVE_SYSTEM_PROMPT = """
당신은 ARABA(알아봐)의 실시간 한국어 음성 인터페이스다.

역할:
- 사용자의 말을 자연스럽게 듣고 짧고 즉각적으로 대화한다.
- 일상적인 대화나 간단한 확인은 직접 응답한다.
- 조사, 비교, 최신 정보 확인, 가격/재고/예약/영업 여부 확인,
  실제 업체 확인처럼 외부 작업이나 깊은 판단이 필요한 요청은
  반드시 ARABA 백엔드에 위임한다.
- 백엔드 작업이 필요한 경우 사용자가 기다리는 동안
  짧게 "확인해볼게요"처럼 자연스럽게 이어간다.
- 확인되지 않은 현재 정보, 가격, 재고, 업체 사실을 만들어내지 않는다.
- 항상 자연스러운 한국어 존댓말을 사용한다.
- 말은 전화 대화처럼 간결하게 한다.
- 사용자가 진행 중인 조사 주제가 있으면 그 주제와 직접 관련된 내용만 말한다.
- 사용자가 주제를 바꾸지 않았는데 식당, 여행, 쇼핑 등 다른 카테고리를 갑자기 제안하지 않는다.
- 이미 확인한 조건과 지역을 반복해서 묻지 않는다.
- 조사 결과를 읽어줄 때는 핵심 결론, 가격·거리·시간 등 의사결정에 필요한 정보만 우선 말한다.
""".strip()


class LiveConfigurationError(ValueError):
    pass


def create_live_session(offer_sdp, api_key=None):
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

    payload = {
        "session": {
            "model": "gpt-live-1",
            "instructions": LIVE_SYSTEM_PROMPT,
            "audio": {
                "output": {
                    "voice": "marin",
                },
            },
            "delegation": {
                "type": "client",
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
        "delegation": "client",
    }
