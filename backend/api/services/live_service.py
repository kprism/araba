import httpx

from .openai_service import get_api_key


OPENAI_LIVE_SESSIONS_URL = "https://api.openai.com/v1/live/sessions"

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
""".strip()


class LiveConfigurationError(ValueError):
    pass


def create_live_session(offer_sdp, api_key=None):
    offer_sdp = str(offer_sdp or "").strip()

    if not offer_sdp:
        raise LiveConfigurationError(
            "GPT-Live 연결용 SDP가 없습니다."
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
    answer_sdp = str(
        data.get("transport", {}).get("sdp", "")
    ).strip()

    if not session_id or not answer_sdp:
        raise LiveConfigurationError(
            "GPT-Live 세션 응답이 올바르지 않습니다."
        )

    return {
        "session_id": session_id,
        "sdp": answer_sdp,
        "model": "gpt-live-1",
        "delegation": "client",
    }
