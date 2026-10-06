import json
import os
from time import monotonic

from openai import OpenAI

from .intent_brain_service import enhance_mission
from .openai_service import get_api_key


INTENT_SYSTEM_PROMPT = """
당신은 ARABA(알아봐)의 Intent Brain이다.

역할은 하나다.
사용자의 현재 발화가 결국 무엇을 하려는 것인지 판단하고,
다음 실행 엔진이 바로 사용할 수 있는 작은 JSON으로 구조화한다.

검색 결과를 직접 만들지 마라.
업체명, 가격, 영업시간, 재고, 예약 가능 여부 같은 외부 사실을 추측하지 마라.
[현재 요청]이 있으면 그것이 항상 최우선이고,
[대화 문맥]은 "그곳", "그중", "아까" 같은 명백한 후속 요청일 때만 필요한 만큼 사용한다.

반드시 JSON 객체 하나만 반환한다.

{
  "intent": "place_search|place_detail|general_answer|web_research|phone_action|image_analysis|document_analysis|conversation|clarify",
  "goal": "사용자가 최종적으로 원하는 결과",
  "location": {
    "value": "지역 또는 기준장소 또는 null",
    "type": "administrative_area|reference_point|none",
    "explicit": true
  },
  "category": "장소검색이면 기본 업종, 아니면 핵심 주제 또는 null",
  "subject": "현재 요청의 핵심 대상 또는 null",
  "target_business": "특정 상호/시설이면 정확한 이름, 아니면 null",
  "count": 5,
  "constraints": ["검색 후 추가로 확인할 조건"],
  "attributes": {},
  "requested_facts": ["사용자가 실제로 알고 싶은 세부 정보"],
  "sort": "relevance|distance|rating|price|none",
  "needs_fresh_data": true,
  "needs_clarification": false,
  "clarification_question": null,
  "direct_answer": null
}

판단 규칙:
1. 치과, 식당, 카페, 병원, 미용실, 타이어점, 관공서, 명소 등 실제 장소나 업체 후보를 찾으려는 요청은 place_search다.
2. place_search에서는 지역과 기본 업종을 분리한다.
   예: "창원시 의창구 중동에서 치과 5곳" -> location.value="창원시 의창구 중동", category="치과", count=5.
3. 서비스 조건을 업종에 섞지 않는다.
   예: "임플란트 가능한 치과" -> category="치과", constraints=["임플란트 가능"].
   "조용한 식당" -> category="식당", constraints=["조용한"].
4. 시/군/구/읍/면/동 같은 행정구역 자체가 범위면 administrative_area다.
   "창원시청 주변", "서울역 근처"처럼 특정 장소를 기준으로 찾으면 reference_point다.
5. 사용자가 특정 상호나 시설 하나를 직접 지목하면 target_business에 정확히 넣는다.
6. 직전에 보여준 장소의 영업시간, 전화, 주소, 가격, 주차 등 세부정보를 묻는 요청은 place_detail다.
7. 사용자가 숫자로 개수를 말하면 count에 그대로 넣는다. 말하지 않으면 null이다.
8. 일반 지식 질문처럼 외부 최신조회가 필요 없으면 general_answer이고 direct_answer에 짧고 정확한 답을 넣는다.
9. 최신 공개정보 조사가 필요하지만 장소검색이 아니면 web_research다.
10. 전화, 예약, 문의 실행이면 phone_action다.
11. clarify는 사용자만 알 수 있는 필수정보가 없고 그것 없이는 서로 전혀 다른 행동으로 갈릴 때만 사용한다.
12. 현재 요청이 새 지역·새 업종을 명시하면 과거 업종이나 상호를 승계하지 않는다.
13. JSON 이외의 설명, Markdown, 코드블록을 출력하지 않는다.
""".strip()


MISSION_MODEL = (
    os.getenv("ARABA_MISSION_MODEL", "gpt-6-luna").strip()
    or "gpt-6-luna"
)
MISSION_TIMEOUT_SECONDS = 12.0

VALID_INTENTS = {
    "place_search",
    "place_detail",
    "general_answer",
    "web_research",
    "phone_action",
    "image_analysis",
    "document_analysis",
    "conversation",
    "clarify",
}
VALID_LOCATION_TYPES = {
    "administrative_area",
    "reference_point",
    "none",
}


def _clean_text(value):
    text = str(value or "").strip()
    return text or None


def _clean_list(value):
    if not isinstance(value, list):
        return []

    result = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)

    return result


def _parse_intent_json(raw):
    text = str(raw or "").strip()

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])

    if not isinstance(value, dict):
        raise ValueError(
            "Intent 응답이 객체 형식이 아닙니다."
        )

    return value


def _normalize_intent(value):
    if not isinstance(value, dict):
        raise ValueError(
            "Intent 응답이 객체 형식이 아닙니다."
        )

    intent = str(value.get("intent") or "").strip()
    if intent not in VALID_INTENTS:
        raise ValueError(
            "Intent 종류가 올바르지 않습니다."
        )

    raw_location = value.get("location")
    location = (
        dict(raw_location)
        if isinstance(raw_location, dict)
        else {}
    )
    location_type = str(
        location.get("type") or "none"
    ).strip()

    if location_type not in VALID_LOCATION_TYPES:
        location_type = "none"

    raw_count = value.get("count")
    try:
        count = (
            int(raw_count)
            if raw_count is not None
            else None
        )
    except (TypeError, ValueError):
        count = None

    if count is not None:
        count = max(1, min(count, 10))

    attributes = value.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}

    return {
        "intent": intent,
        "goal": _clean_text(value.get("goal")) or "",
        "location": {
            "value": _clean_text(location.get("value")),
            "type": location_type,
            "explicit": location.get("explicit") is True,
        },
        "category": _clean_text(value.get("category")),
        "subject": _clean_text(value.get("subject")),
        "target_business": _clean_text(
            value.get("target_business")
        ),
        "count": count,
        "constraints": _clean_list(
            value.get("constraints")
        ),
        "attributes": dict(attributes),
        "requested_facts": _clean_list(
            value.get("requested_facts")
        ),
        "sort": (
            str(value.get("sort") or "none").strip()
            or "none"
        ),
        "needs_fresh_data": (
            value.get("needs_fresh_data") is True
        ),
        "needs_clarification": (
            value.get("needs_clarification") is True
        ),
        "clarification_question": _clean_text(
            value.get("clarification_question")
        ),
        "direct_answer": _clean_text(
            value.get("direct_answer")
        ),
    }


def _create_intent_response(
    client,
    *,
    request_text,
):
    return client.responses.create(
        model=MISSION_MODEL,
        instructions=INTENT_SYSTEM_PROMPT,
        input=request_text,
        max_output_tokens=700,
    )


def _place_mission(intent):
    location = intent["location"]["value"]
    location_type = intent["location"]["type"]
    category = (
        intent["category"]
        or intent["subject"]
        or "장소"
    )
    target_business = intent["target_business"]
    requested_count = intent["count"] or 5

    if target_business:
        search_mode = "exact_place"
        search_terms = [target_business]
    else:
        search_mode = (
            "area_discovery"
            if location_type == "reference_point"
            else "category_discovery"
        )
        search_terms = [category]

    required_facts = (
        list(intent["requested_facts"])
        if intent["requested_facts"]
        else ["후보 장소", "주소", "전화번호"]
    )

    if (
        location_type == "reference_point"
        and "거리" not in required_facts
    ):
        required_facts.append("거리")

    subject = intent["subject"] or category
    goal = (
        intent["goal"]
        or f"{location or ''} {subject} 후보를 찾는다.".strip()
    )

    mission = {
        "title": goal,
        "summary": goal,
        "category": category,
        "subcategories": [category],
        "intent": "place_search",
        "search_mode": search_mode,
        "response_mode": "research",
        "direct_answer": None,
        "location": location,
        "location_explicit": intent["location"]["explicit"],
        "subject": subject,
        "target_business": target_business,
        "attributes": intent["attributes"],
        "constraints": intent["constraints"],
        "comparison": intent["sort"],
        "search_terms": search_terms,
        "requested_count": requested_count,
        "required_facts": required_facts,
        "needs_fresh_data": True,
        "may_need_phone_call": False,
        "missing_information": [],
        "clarification_questions": [],
        "ready_to_research": True,
        "user_goal": goal,
        "decision_needed": (
            "요청한 지역·업종·조건에 맞는 실제 장소만 확정한다."
        ),
        "known_facts": {
            "location": location,
            "category": category,
            "requested_count": requested_count,
        },
        "unknown_facts": list(required_facts),
        "research_plan": [
            {
                "step": 1,
                "goal": "실제 장소 후보를 수집한다.",
                "tool": "place_search",
                "when": "항상",
            },
            {
                "step": 2,
                "goal": (
                    "지역·업종 적합성을 검증하고 "
                    "중복 제거 후 요청 개수만 남긴다."
                ),
                "tool": "map",
                "when": "후보를 받은 뒤",
            },
        ],
        "completion_criteria": [
            "지역과 기본 업종이 모두 일치하는 후보만 남는다.",
            "중복 제거 후 요청한 개수 이하의 검증된 후보를 제시한다.",
        ],
        "confidence_target": "high",
        "location_context": {
            "value": location,
            "type": location_type,
            "radius_hint_km": (
                3
                if location_type == "reference_point"
                else None
            ),
        },
        "intent_brain": intent,
    }

    mission = enhance_mission(
        mission,
        goal,
    )
    mission["brain_version"] = "intent-router-v2"
    return mission


def _place_detail_mission(intent):
    target = intent["target_business"]

    if not target:
        question = (
            intent["clarification_question"]
            or "어느 장소를 말씀하시는지 알려주세요."
        )
        return {
            "title": "장소 확인",
            "summary": intent["goal"],
            "category": intent["category"] or "장소",
            "subcategories": [],
            "intent": "clarify",
            "search_mode": "follow_up_detail",
            "response_mode": "clarify",
            "direct_answer": None,
            "location": intent["location"]["value"],
            "location_explicit": intent["location"]["explicit"],
            "subject": intent["subject"],
            "target_business": None,
            "attributes": intent["attributes"],
            "constraints": intent["constraints"],
            "comparison": "none",
            "search_terms": [],
            "requested_count": 1,
            "required_facts": intent["requested_facts"],
            "needs_fresh_data": True,
            "may_need_phone_call": False,
            "missing_information": ["대상 장소"],
            "clarification_questions": [
                {
                    "question": question,
                    "options": [],
                }
            ],
            "ready_to_research": False,
            "intent_brain": intent,
            "brain_version": "intent-router-v2",
        }

    facts = (
        intent["requested_facts"]
        or ["요청한 장소 상세정보"]
    )

    mission = {
        "title": f"{target} 상세 확인",
        "summary": (
            intent["goal"]
            or f"{target} 상세정보를 확인한다."
        ),
        "category": intent["category"] or "장소",
        "subcategories": [],
        "intent": "place_detail",
        "search_mode": "follow_up_detail",
        "response_mode": "research",
        "direct_answer": None,
        "location": intent["location"]["value"],
        "location_explicit": intent["location"]["explicit"],
        "subject": intent["subject"] or target,
        "target_business": target,
        "attributes": intent["attributes"],
        "constraints": intent["constraints"],
        "comparison": "none",
        "search_terms": [target],
        "requested_count": 1,
        "required_facts": facts,
        "needs_fresh_data": True,
        "may_need_phone_call": False,
        "missing_information": [],
        "clarification_questions": [],
        "ready_to_research": True,
        "research_plan": [
            {
                "step": 1,
                "goal": f"{target}의 실제 장소정보를 확인한다.",
                "tool": "place_search",
                "when": "항상",
            }
        ],
        "location_context": {
            "value": intent["location"]["value"],
            "type": intent["location"]["type"],
            "radius_hint_km": None,
        },
        "intent_brain": intent,
    }

    mission = enhance_mission(
        mission,
        intent["goal"],
    )
    mission["brain_version"] = "intent-router-v2"
    return mission


def _non_place_mission(intent):
    needs_clarification = (
        intent["needs_clarification"]
        or intent["intent"] == "clarify"
    )

    if needs_clarification:
        question = (
            intent["clarification_question"]
            or "진행에 꼭 필요한 정보를 조금만 더 알려주세요."
        )
        return {
            "title": "추가 확인",
            "summary": intent["goal"],
            "category": intent["category"] or "기타",
            "subcategories": [],
            "intent": intent["intent"],
            "search_mode": "general",
            "response_mode": "clarify",
            "direct_answer": None,
            "location": intent["location"]["value"],
            "location_explicit": intent["location"]["explicit"],
            "subject": intent["subject"],
            "target_business": intent["target_business"],
            "attributes": intent["attributes"],
            "constraints": intent["constraints"],
            "comparison": intent["sort"],
            "search_terms": [],
            "requested_count": intent["count"],
            "required_facts": intent["requested_facts"],
            "needs_fresh_data": intent["needs_fresh_data"],
            "may_need_phone_call": (
                intent["intent"] == "phone_action"
            ),
            "missing_information": [question],
            "clarification_questions": [
                {
                    "question": question,
                    "options": [],
                }
            ],
            "ready_to_research": False,
            "intent_brain": intent,
            "brain_version": "intent-router-v2",
        }

    direct_answer = intent["direct_answer"]

    if not direct_answer:
        if intent["intent"] == "web_research":
            direct_answer = (
                "이 요청은 최신 웹 조사가 필요한 유형으로 판단했어요. "
                "웹 조사 엔진에서 이어서 처리해야 합니다."
            )
        elif intent["intent"] == "phone_action":
            direct_answer = (
                "전화 실행 요청으로 판단했어요. "
                "대상 장소와 실행 조건을 기준으로 이어서 처리할게요."
            )
        else:
            direct_answer = (
                intent["goal"]
                or "요청을 이해했어요."
            )

    mission = {
        "title": intent["goal"] or "요청 처리",
        "summary": intent["goal"],
        "category": intent["category"] or "기타",
        "subcategories": [],
        "intent": intent["intent"],
        "search_mode": "general",
        "response_mode": "answer",
        "direct_answer": direct_answer,
        "location": intent["location"]["value"],
        "location_explicit": intent["location"]["explicit"],
        "subject": intent["subject"],
        "target_business": intent["target_business"],
        "attributes": intent["attributes"],
        "constraints": intent["constraints"],
        "comparison": intent["sort"],
        "search_terms": [],
        "requested_count": intent["count"],
        "required_facts": intent["requested_facts"],
        "needs_fresh_data": intent["needs_fresh_data"],
        "may_need_phone_call": (
            intent["intent"] == "phone_action"
        ),
        "missing_information": [],
        "clarification_questions": [],
        "ready_to_research": False,
        "intent_brain": intent,
    }

    mission = enhance_mission(
        mission,
        intent["goal"],
    )
    mission["brain_version"] = "intent-router-v2"
    return mission


def _mission_from_intent(intent):
    if intent["intent"] == "place_search":
        return _place_mission(intent)

    if intent["intent"] == "place_detail":
        return _place_detail_mission(intent)

    return _non_place_mission(intent)


def create_mission(
    user_request,
    api_key=None,
    *,
    diagnostics=None,
):
    diagnostics = (
        diagnostics
        if diagnostics is not None
        else {}
    )
    diagnostics["stage"] = "request_validation"

    request_text = str(
        user_request or ""
    ).strip()

    if not request_text:
        raise ValueError(
            "알아볼 내용을 입력해주세요."
        )

    api_key = get_api_key(api_key)
    if not api_key:
        raise ValueError(
            "OpenAI API Key가 설정되지 않았습니다."
        )

    diagnostics["architecture"] = "intent_router_v2"
    diagnostics["stage"] = "intent_core_request"

    client = OpenAI(
        api_key=api_key,
        timeout=MISSION_TIMEOUT_SECONDS,
        max_retries=0,
    )

    call_started = monotonic()
    try:
        response = _create_intent_response(
            client,
            request_text=request_text,
        )
    finally:
        diagnostics["openai_elapsed_ms"] = round(
            (monotonic() - call_started) * 1000
        )

    diagnostics["stage"] = "parse_intent"

    try:
        intent = _normalize_intent(
            _parse_intent_json(
                response.output_text
            )
        )
    except (
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "OpenAI가 Intent JSON을 올바르게 반환하지 않았습니다."
        ) from exc

    diagnostics["stage"] = "route_intent"
    diagnostics["route"] = intent["intent"]

    return _mission_from_intent(intent)
