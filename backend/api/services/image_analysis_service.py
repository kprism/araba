import base64
import json

from openai import OpenAI

from .openai_service import get_api_key


def analyze_image_bytes(image_bytes, *, mime_type, context, api_key=None):
    if not image_bytes:
        raise ValueError("판독할 이미지가 없습니다.")

    key = get_api_key(api_key)
    if not key:
        raise ValueError("OpenAI API Key가 필요합니다.")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"

    client = OpenAI(api_key=key, timeout=45.0, max_retries=0)
    response = client.responses.create(
        model="gpt-5-mini",
        instructions=(
            "사진에서 현재 조사에 필요한 정보만 판독한다. "
            "차량에 한정하지 말고 영수증, 제품라벨, 명함, 안내문, 예약문자, "
            "고장화면 등 실생활 이미지를 처리한다. "
            "확실하지 않은 내용은 추측하지 않는다. "
            "JSON으로 summary, attributes, visible_text, confidence, warnings를 반환한다."
        ),
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": f"현재 조사 문맥: {context}"},
                {"type": "input_image", "image_url": data_url, "detail": "high"},
            ],
        }],
        max_output_tokens=1200,
    )

    raw = response.output_text.strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("이미지 판독 결과 형식이 올바르지 않습니다.")

    if not isinstance(data.get("attributes"), dict):
        data["attributes"] = {}
    if not isinstance(data.get("visible_text"), list):
        data["visible_text"] = []
    if not isinstance(data.get("warnings"), list):
        data["warnings"] = []

    return data
