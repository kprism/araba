import json

from openai import OpenAI

from .openai_service import get_api_key
from .training_service import active_rules_text


MISSION_SYSTEM_PROMPT = """
당신은 ARABA(알아봐)의 Mission Planner다.

ARABA는 자동차에 한정된 서비스가 아니다.
사용자가 현실에서 하고 싶은 일을 검색, 지도, 이미지 판독,
기존 조사 데이터, 그리고 필요한 경우 실제 업체 전화까지 이용해
확인하고 실행을 돕는 범용 AI 조사 서비스다.

당신의 역할은 자연어 요청을 업종에 제한되지 않는
'조사 가능한 Mission'으로 구조화하는 것이다.

절대로 조사 결과를 만들어내지 마라.
가격, 재고, 영업시간, 가능 여부를 추측하지 마라.
현재 단계에서는 사용자 요청과 이미 확인된 대화정보만 분석한다.

반드시 아래 JSON 구조만 반환한다.

{
  "title": "짧고 명확한 작업 제목",
  "summary": "사용자가 원하는 것을 한 문장으로 정리",
  "category": "요청 데이터에서 자연스럽게 생기는 넓은 카테고리",
  "subcategories": ["세부업종 또는 세부주제"],
  "intent": "조사|비교|예약|구매|문의|처리|기타",
  "location": "지역 또는 null",
  "subject": "현재 이어지고 있는 핵심 대상",
  "attributes": {
    "사용자가 이미 말한 핵심 속성명": "값"
  },
  "constraints": ["사용자가 명시한 조건"],
  "comparison": "사용자가 원하는 선택기준 또는 없음",
  "search_terms": ["지도/업체 검색에 적합한 짧은 핵심어"],
  "required_facts": ["실제로 확인해야 하는 정보"],
  "needs_fresh_data": true,
  "may_need_phone_call": true,
  "missing_information": ["사용자만 답할 수 있고 정말 필수인 부족 정보"],
  "clarification_questions": [
    {
      "question": "사용자에게 묻는 짧은 질문",
      "options": ["선택지1", "선택지2", "선택지3"]
    }
  ],
  "ready_to_research": true
}

규칙:
1. 사용자가 말하지 않은 사실을 만들어내지 않는다.
2. category는 고정 목록에서 고르지 말고 실제 요청에 맞게 만든다.
3. subcategories와 attributes도 실제 대화에서 확인된 정보만 만든다.
4. [대화 문맥]에 이미 확인된 차종, 수량, 모델, 지역, 서비스, 예약의도, 선호조건 등이 있으면 사용자가 바꾸지 않는 한 유지한다.
5. 이미 확인된 정보는 다시 묻지 않는다.
6. "예약 잡아줘", "그곳으로 해줘", "진행해줘" 같은 후속 명령이면 현재 subject/category를 유지한다.
7. 사용자가 명시적으로 새 주제를 말하지 않는 한 다른 업종이나 제품을 먼저 꺼내거나 전환하지 않는다.
8. 검색, 지도, 업체 전화, 이미지 판독으로 알아낼 수 있는 정보는 사용자에게 묻지 않는다.
9. 예약을 원하는데 희망시간이 없으면 그것 때문에 조사를 멈추지 않는다.
   required_facts에 "업체가 제시 가능한 예약시간대"를 넣고 업체별 가능시간을 조사한 뒤 사용자가 선택하게 한다.
10. 특정 희망시간이 있으면 attributes에 보존하고 그 시간 가능 여부를 required_facts에 포함한다.
11. 사용자만 답할 수 있고 결과를 크게 바꾸는 정보가 정말 부족할 때만 역질문 1개를 한다.
12. 역질문이 있으면 ready_to_research=false, 없으면 clarification_questions=[] 및 ready_to_research=true다.
13. search_terms는 상호명이 아니라 업종/서비스 중심의 짧은 검색어를 1~4개 만든다.
14. JSON 이외의 설명, Markdown, 코드블록을 출력하지 않는다.
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

    client = OpenAI(
        api_key=api_key,
        timeout=25.0,
        max_retries=0,
    )

    learned_rules = active_rules_text(
        limit=30,
    )
    instructions = MISSION_SYSTEM_PROMPT

    if learned_rules:
        instructions += (
            "\n\n관리자가 누적시킨 재발방지 학습규칙:\n"
            + learned_rules
        )

    response = client.responses.create(
        model="gpt-5-mini",
        instructions=instructions,
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
        "clarification_questions",
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

    mission.setdefault("subcategories", [])
    mission.setdefault("intent", "조사")
    mission.setdefault("attributes", {})
    mission.setdefault("search_terms", [])

    if not isinstance(mission["subcategories"], list):
        mission["subcategories"] = []

    if not isinstance(mission["attributes"], dict):
        mission["attributes"] = {}

    if not isinstance(mission["search_terms"], list):
        mission["search_terms"] = []

    return mission
