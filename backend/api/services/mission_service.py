import json

from openai import OpenAI

from .openai_service import get_api_key


MISSION_SYSTEM_PROMPT = """
당신은 ARABA(알아봐)의 Mission Planner다.

ARABA는 사용자가 현실에서 알고 싶은 정보를
웹, 기존 데이터, 그리고 필요한 경우 실제 업체 전화까지 이용해
확인하는 AI 조사 서비스다.

당신의 역할은 사용자의 자연어 요청을
'조사 가능한 Mission'으로 구조화하는 것이다.

절대로 조사 결과를 만들어내지 마라.
가격, 재고, 영업시간, 가능 여부 등을 추측하지 마라.
현재 단계에서는 오직 사용자의 요청을 분석한다.

반드시 아래 JSON 구조만 반환한다.

{
  "title": "짧고 명확한 작업 제목",
  "summary": "사용자가 원하는 것을 한 문장으로 정리",
  "category": "자동차|음식점|쇼핑|예약|생활서비스|여행|의료|기타",
  "location": "지역 또는 null",
  "subject": "찾으려는 대상",
  "constraints": [
    "사용자가 명시한 조건"
  ],
  "comparison": "최저가격|최고평점|가장빠른가능시간|거리|조건비교|없음",
  "required_facts": [
    "실제로 확인해야 하는 정보"
  ],
  "needs_fresh_data": true,
  "may_need_phone_call": true,
  "missing_information": [
    "조사를 위해 추가로 필요한 정보"
  ],
  "ready_to_research": true
}

규칙:
1. 사용자가 말하지 않은 사실을 만들어내지 않는다.
2. 상대적인 날짜 표현은 그대로 보존해도 된다.
3. 전화가 필요할 가능성이 있으면 may_need_phone_call=true.
4. 웹 정보만으로 오래되었을 가능성이 있는 가격, 재고,
   예약 가능시간, 당일 작업 가능 여부 등은 needs_fresh_data=true.
5. 정보가 부족해 조사를 시작할 수 없으면
   ready_to_research=false로 한다.
6. missing_information에는 정말 필요한 정보만 넣는다.
7. JSON 이외의 설명, Markdown, 코드블록을 출력하지 않는다.
""".strip()


def create_mission(user_request, api_key=None):
    request_text = str(user_request).strip()

    if not request_text:
        raise ValueError("알아볼 내용을 입력해주세요.")

    api_key = get_api_key(api_key)

    if not api_key:
        raise ValueError(
            "OpenAI API Key가 설정되지 않았습니다."
        )

    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model="gpt-5-mini",
        instructions=MISSION_SYSTEM_PROMPT,
        input=request_text,
    )

    raw = response.output_text.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json")
        raw = raw.removeprefix("```")
        raw = raw.removesuffix("```").strip()

    try:
        mission = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "OpenAI가 Mission JSON을 올바르게 반환하지 않았습니다."
        ) from exc

    required_keys = {
        "title",
        "summary",
        "category",
        "location",
        "subject",
        "constraints",
        "comparison",
        "required_facts",
        "needs_fresh_data",
        "may_need_phone_call",
        "missing_information",
        "ready_to_research",
    }

    missing_keys = sorted(
        required_keys - set(mission.keys())
    )

    if missing_keys:
        raise ValueError(
            "Mission 필수 항목이 누락되었습니다: "
            + ", ".join(missing_keys)
        )

    return mission
