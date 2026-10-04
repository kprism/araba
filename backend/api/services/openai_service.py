import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT_DIR / ".env"


def reload_environment():
    load_dotenv(ENV_FILE, override=True)


def get_api_key(api_key=None):
    provided_key = str(api_key or "").strip()

    if provided_key:
        return provided_key

    reload_environment()
    return os.getenv("OPENAI_API_KEY", "").strip()


def mask_api_key(key):
    if not key:
        return None

    if len(key) <= 12:
        return "********"

    return f"{key[:7]}••••••••••••{key[-4:]}"


def get_openai_status(api_key=None):
    key = get_api_key(api_key)

    return {
        "configured": bool(key),
        "masked": mask_api_key(key),
    }


def test_openai_connection(api_key=None):
    key = get_api_key(api_key)

    if not key:
        raise ValueError(
            "OpenAI API Key가 설정되지 않았습니다."
        )

    client = OpenAI(api_key=key)

    # 실제 인증 요청.
    # 모델 목록 조회만 하므로 생성 토큰을 소비하지 않는다.
    models = client.models.list()

    return {
        "connected": True,
        "model_count": len(models.data),
        "masked": mask_api_key(key),
    }
