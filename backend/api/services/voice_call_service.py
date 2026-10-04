import base64
import hashlib
import os
import re
from urllib.parse import urlencode

from cryptography.fernet import Fernet
from django.conf import settings
from django.core import signing
from openai import OpenAI
from twilio.rest import Client
from twilio.twiml.voice_response import Gather, VoiceResponse


VOICE_SESSION_SALT = "araba.voice.test-call"
DEFAULT_PUBLIC_BASE_URL = (
    "https://araba-api-dev-908580697493."
    "asia-northeast3.run.app"
)
VOICE_SYSTEM_PROMPT = """
당신은 ARABA의 전화 통화용 한국어 AI다.

현재 통화는 실제 업체 전화 기능을 만들기 전,
사용자 본인과 진행하는 AI 음성통화 POC 테스트다.

규칙:
1. 항상 자연스러운 한국어 존댓말로 답한다.
2. 전화 통화이므로 답변은 짧게, 보통 1~3문장으로 한다.
3. 사용자가 말한 내용에 직접 반응하고, 필요하면 짧은 질문 1개를 한다.
4. Markdown, 목록 기호, 이모지를 쓰지 않는다.
5. 가격·재고·업체 정보처럼 확인하지 않은 사실은 만들어내지 않는다.
6. 사용자가 "그만", "종료", "끊어", "전화 끊어"라고 하면
   짧게 인사하고 통화를 끝낼 수 있도록 말한다.
""".strip()


class VoiceConfigurationError(ValueError):
    pass


def _env(name):
    return os.getenv(name, "").strip()


def _server_openai_key():
    return (
        _env("VOICE_OPENAI_API_KEY")
        or _env("OPENAI_API_KEY")
    )


def _fernet():
    digest = hashlib.sha256(
        settings.SECRET_KEY.encode("utf-8")
    ).digest()

    return Fernet(
        base64.urlsafe_b64encode(digest)
    )


def _encrypt_secret(value):
    return _fernet().encrypt(
        str(value).encode("utf-8")
    ).decode("ascii")


def _decrypt_secret(value):
    return _fernet().decrypt(
        str(value).encode("ascii")
    ).decode("utf-8")


def voice_configuration_status():
    return {
        "ready": True,
        "credential_mode": "device",
        "server_openai_fallback": bool(
            _server_openai_key()
        ),
    }


def normalize_phone_number(value):
    raw = str(value or "").strip()
    compact = re.sub(r"[\s\-().]", "", raw)

    if compact.startswith("010"):
        compact = "+82" + compact[1:]
    elif compact.startswith("82"):
        compact = "+" + compact
    elif not compact.startswith("+"):
        raise ValueError(
            "휴대폰 번호는 010-1234-5678 또는 +821012345678 형식으로 입력해주세요."
        )

    if not re.fullmatch(r"\+[1-9]\d{7,14}", compact):
        raise ValueError("휴대폰 번호 형식이 올바르지 않습니다.")

    return compact


def _public_base_url():
    return (
        _env("ARABA_PUBLIC_BASE_URL")
        or DEFAULT_PUBLIC_BASE_URL
    ).rstrip("/")


def _voice_url(path, **query):
    url = f"{_public_base_url()}{path}"

    if query:
        url += "?" + urlencode(query)

    return url


def _create_session_token(phone_number, api_key):
    return signing.dumps(
        {
            "phone": phone_number,
            "openai_key": _encrypt_secret(api_key),
        },
        salt=VOICE_SESSION_SALT,
        compress=True,
    )


def _validate_session_token(token):
    try:
        data = signing.loads(
            token,
            salt=VOICE_SESSION_SALT,
            max_age=60 * 60,
        )
    except signing.BadSignature as exc:
        raise ValueError("유효하지 않은 음성통화 세션입니다.") from exc

    encrypted_key = str(
        data.get("openai_key", "")
    ).strip()

    if not encrypted_key:
        raise ValueError(
            "음성통화용 OpenAI 키가 없습니다."
        )

    data["openai_key"] = _decrypt_secret(
        encrypted_key
    )
    return data


def _say(response_or_gather, text):
    response_or_gather.say(
        text,
        language="ko-KR",
        voice="Polly.Seoyeon-Neural",
    )


def _should_end_call(speech):
    normalized = re.sub(r"\s+", "", speech)

    return any(
        phrase in normalized
        for phrase in (
            "그만",
            "종료",
            "끊어",
            "전화끊어",
            "통화종료",
        )
    )


def _find_twilio_from_number(client):
    configured = (
        _env("TWILIO_PHONE_NUMBER")
        or _env("TWILIO_FROM_NUMBER")
    )

    if configured:
        return configured

    numbers = client.incoming_phone_numbers.list(
        limit=20
    )

    for number in numbers:
        phone = str(
            getattr(number, "phone_number", "")
        ).strip()

        capabilities = (
            getattr(number, "capabilities", {})
            or {}
        )

        if (
            phone
            and (
                capabilities.get("voice") is True
                or capabilities.get("Voice") is True
                or not capabilities
            )
        ):
            return phone

    raise VoiceConfigurationError(
        "Twilio 발신번호가 없습니다. "
        "Twilio Console에서 Voice 가능한 전화번호를 먼저 받아주세요."
    )


def start_test_call(
    phone_number,
    *,
    account_sid,
    auth_token,
    api_key,
):
    account_sid = str(account_sid).strip()
    auth_token = str(auth_token).strip()
    api_key = str(api_key).strip()

    if not account_sid or not auth_token:
        raise VoiceConfigurationError(
            "Twilio Account SID와 Auth Token이 필요합니다."
        )

    if not api_key:
        raise VoiceConfigurationError(
            "OpenAI API Key가 필요합니다."
        )

    to_number = normalize_phone_number(
        phone_number
    )
    session = _create_session_token(
        to_number,
        api_key,
    )

    client = Client(
        account_sid,
        auth_token,
    )
    from_number = _find_twilio_from_number(
        client
    )

    call = client.calls.create(
        to=to_number,
        from_=from_number,
        url=_voice_url(
            "/api/voice/answer/",
            session=session,
        ),
        method="POST",
    )

    return {
        "call_sid": call.sid,
        "to": to_number,
        "status": getattr(call, "status", None),
    }


def build_answer_twiml(session_token):
    _validate_session_token(session_token)

    response = VoiceResponse()
    action = _voice_url(
        "/api/voice/respond/",
        session=session_token,
    )

    gather = Gather(
        input="speech",
        action=action,
        method="POST",
        language="ko-KR",
        speech_timeout="auto",
        timeout=6,
        action_on_empty_result=True,
    )

    _say(
        gather,
        (
            "안녕하세요. 아라바 AI 음성통화 테스트입니다. "
            "지금부터 저와 자연스럽게 대화해 보세요. "
            "먼저 아무 말씀이나 해주세요."
        ),
    )
    response.append(gather)

    _say(
        response,
        "말씀이 들리지 않았어요. 테스트 통화를 종료할게요.",
    )
    response.hangup()

    return str(response)


def _generate_voice_reply(
    speech,
    *,
    api_key,
    previous_response_id=None,
):
    api_key = str(api_key or "").strip()

    if not api_key:
        api_key = _server_openai_key()

    if not api_key:
        raise VoiceConfigurationError(
            "음성통화용 OpenAI API Key가 없습니다."
        )

    client = OpenAI(
        api_key=api_key,
        timeout=30.0,
        max_retries=1,
    )

    kwargs = {
        "model": _env("VOICE_OPENAI_MODEL") or "gpt-5-mini",
        "instructions": VOICE_SYSTEM_PROMPT,
        "input": speech,
        "max_output_tokens": 120,
    }

    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id

    response = client.responses.create(**kwargs)
    reply = response.output_text.strip()

    if not reply:
        reply = "네, 잘 들었습니다. 한 말씀만 더 해주세요."

    return {
        "response_id": response.id,
        "reply": reply[:700],
    }


def build_response_twiml(
    session_token,
    speech,
    previous_response_id=None,
):
    session = _validate_session_token(
        session_token
    )

    speech = str(speech or "").strip()
    response = VoiceResponse()

    if not speech:
        _say(
            response,
            "말씀을 잘 듣지 못했어요. 다시 한 번 전화 테스트를 해주세요.",
        )
        response.hangup()
        return str(response)

    if _should_end_call(speech):
        _say(
            response,
            "네, 음성통화 테스트를 마칠게요. 감사합니다.",
        )
        response.hangup()
        return str(response)

    ai = _generate_voice_reply(
        speech,
        api_key=session["openai_key"],
        previous_response_id=previous_response_id,
    )

    next_action = _voice_url(
        "/api/voice/respond/",
        session=session_token,
        previous_response_id=ai["response_id"],
    )

    gather = Gather(
        input="speech",
        action=next_action,
        method="POST",
        language="ko-KR",
        speech_timeout="auto",
        timeout=6,
        action_on_empty_result=True,
    )

    _say(gather, ai["reply"])
    response.append(gather)

    _say(
        response,
        "추가 말씀이 없어 테스트 통화를 종료할게요.",
    )
    response.hangup()

    return str(response)
