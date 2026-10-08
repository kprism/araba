import json
import os
import re
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
  "search_terms": ["장소검색에서 실제 검색할 구체 업종·메뉴·서비스어"],
  "target_business": "특정 상호/시설이면 정확한 이름, 아니면 null",
  "count": 5,
  "constraints": ["검색 후 추가로 확인할 조건"],
  "criteria": [
    {
      "field": "parking_available|closing_time|opening_time|price|distance_m|availability|stock|service|rating|custom",
      "operator": "eq|contains|gte|lte|min|max|exists",
      "value": true,
      "required": true,
      "label": "사용자 조건을 사람이 읽을 수 있는 문장"
    }
  ],
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
3-1. 사용자가 후보를 고르기 위한 조건을 말하면 criteria에도 구조화한다.
   예: "주차되고 8시 이후까지 하는 치과" ->
   criteria=[
     {"field":"parking_available","operator":"eq","value":true,"required":true,"label":"주차 가능"},
     {"field":"closing_time","operator":"gte","value":"20:00","required":true,"label":"20시 이후 영업"}
   ].
   "10만원 이하"는 field="price", operator="lte", value=100000 으로 만든다.
   "가장 늦게", "가장 싸게", "가장 가까운"처럼 순위를 고르는 조건은 각각 operator="max" 또는 "min"으로 만든다.
   데이터로 판정할 수 없는 주관 조건은 field="custom"으로 남기고 추측하지 않는다.
4. 시/군/구/읍/면/동 같은 행정구역 자체가 범위면 administrative_area다.
   "창원시청 주변", "서울역 근처"처럼 특정 장소를 기준으로 찾으면 reference_point다.
5. 사용자가 특정 상호나 시설 하나를 직접 지목하면 target_business에 정확히 넣는다.
6. 직전에 보여준 장소의 영업시간, 전화, 주소, 가격, 주차 등 세부정보를 묻는 요청은 place_detail다.
7. 사용자가 숫자로 개수를 말하면 count에 그대로 넣는다. 말하지 않으면 null이다.
8. 일반 지식 질문처럼 외부 최신조회가 필요 없으면 general_answer이고 direct_answer에 짧고 정확한 답을 넣는다.
9. 최신 공개정보 조사가 필요하지만 장소검색이 아니면 web_research다.
10. 전화, 예약, 문의 실행이면 phone_action다.
11. 목표는 이해했지만 그 목표를 제대로 실행하려면 사용자만 알 수 있는 중요한 정보가 빠져 있으면 기다리지 말고 적극적으로 한 가지씩 질문한다. 검색으로 알아낼 수 있는 사실은 사용자에게 묻지 않는다. 결과를 크게 바꾸는 정보만 묻는다.
    예: "치과 찾아줘"인데 지역이 전혀 없으면 "어느 지역이나 기준 장소 주변에서 찾을까요?"라고 묻는다.
    예: 예약이 목표인데 날짜·시간·인원 중 실제 예약에 꼭 필요한 정보가 빠졌다면 가장 중요한 것 하나만 먼저 묻고, 사용자의 답을 기존 목표에 합쳐 다음 판단을 한다.
    이미 답한 정보는 다시 묻지 않고, 한 번에 여러 질문을 쏟아내지 않는다.
12. 현재 요청이 새 지역·새 업종을 명시하면 과거 업종이나 상호를 승계하지 않는다.
13. [대화 문맥]의 recent_place_results 또는 recent_place_searches에
    직전 장소검색 결과가 있으면 "첫 번째", "두 번째", "그곳", "거기",
    "아까 치과", "아까 미용실" 같은 후속표현을 해당 결과의 실제 상호명으로 해석한다.
    특정 순번이나 한 업체의 주소·전화·영업시간·주차·가격 등을 묻는 경우
    intent=place_detail로 하고 target_business에는 문맥에 있는 정확한 상호명을 넣는다.
14. 사용자가 새 업종을 말하면 recent_place_results의 직전 업종에 끌려가지 않는다.
15. "거기 아니고 X", "X 말고 Y", "지역은 Y야", "아니, Y에서"처럼 사용자가 장소나 지역을 정정하면 이전 위치를 폐기하고 정정한 위치를 현재 요청의 location으로 사용한다. 정정된 위치는 explicit=true로 처리하고, 직전 검색 결과를 재사용하지 말고 새 위치에서 다시 조사한다.
16. 한 발화 안에서 사용자가 말을 고친 경우 마지막 정정이 최종 의도다. "쌈밥이 아니고 국밥집"이면 쌈밥은 완전히 버리고 category="식당", subject="국밥집", search_terms=["국밥"]처럼 구조화한다. "치과 말고 피부과"면 치과를 버리고 피부과만 남긴다. 부정되거나 취소된 단어를 category, subject, search_terms, constraints에 남기지 않는다.
17. 음식 종류처럼 기본 업종보다 구체적인 검색어가 있으면 category에는 넓은 업종(예: 식당)을 두고 search_terms에는 실제 찾을 말(예: 국밥, 냉면, 초밥)을 넣는다.
18. JSON 이외의 설명, Markdown, 코드블록을 출력하지 않는다.
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


def _clean_criteria(value):
    if not isinstance(value, list):
        return []

    allowed_operators = {
        "eq",
        "contains",
        "gte",
        "lte",
        "min",
        "max",
        "exists",
    }
    result = []

    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue

        field = str(item.get("field") or "").strip()
        operator = str(item.get("operator") or "eq").strip().lower()
        if not field or operator not in allowed_operators:
            continue

        raw_value = item.get("value")
        if isinstance(raw_value, (dict, list)):
            continue

        label = str(item.get("label") or "").strip()
        result.append(
            {
                "id": str(item.get("id") or f"c{index + 1}"),
                "field": field,
                "operator": operator,
                "value": raw_value,
                "required": item.get("required") is not False,
                "label": label or field,
            }
        )

    return result[:12]


def _task_state_for(mission):
    criteria = mission.get("criteria")
    if not isinstance(criteria, list):
        criteria = []

    if mission.get("response_mode") == "clarify":
        stage = "needs_clarification"
    elif mission.get("ready_to_research") is True:
        stage = "research_ready"
    else:
        stage = "answer_ready"

    attributes = mission.get("attributes")
    reuse_recent = (
        isinstance(attributes, dict)
        and attributes.get("reuse_recent_results") is True
    )

    return {
        "version": "task-state-v1",
        "goal": str(
            mission.get("user_goal")
            or mission.get("summary")
            or mission.get("title")
            or ""
        ).strip(),
        "stage": stage,
        "intent": str(mission.get("intent") or "").strip(),
        "category": mission.get("category"),
        "location": mission.get("location"),
        "target_business": mission.get("target_business"),
        "requested_count": mission.get("requested_count"),
        "constraints": list(mission.get("constraints") or []),
        "criteria": [dict(item) for item in criteria if isinstance(item, dict)],
        "required_facts": list(mission.get("required_facts") or []),
        "missing_information": list(
            mission.get("missing_information") or []
        ),
        "next_question": (
            (
                mission.get("clarification_questions") or [{}]
            )[0].get("question")
            if isinstance(
                (mission.get("clarification_questions") or [{}])[0],
                dict,
            )
            else None
        ),
        "candidate_scope": (
            "recent_results"
            if reuse_recent
            else "new_search"
        ),
    }


def _attach_task_state(mission):
    mission = dict(mission)
    mission["task_state"] = _task_state_for(mission)
    return mission


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
        "search_terms": _clean_list(
            value.get("search_terms")
        ),
        "target_business": _clean_text(
            value.get("target_business")
        ),
        "count": count,
        "constraints": _clean_list(
            value.get("constraints")
        ),
        "criteria": _clean_criteria(
            value.get("criteria")
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


SELF_CORRECTION_RE = re.compile(
    r"([0-9a-zA-Z가-힣]{2,20}?)(?:이|가)?\s*(?:아니고|말고)\s*[,，]?\s*([0-9a-zA-Z가-힣]{2,20})"
)

FOOD_PLACE_TERMS = {
    "식당",
    "음식점",
    "맛집",
    "밥집",
    "레스토랑",
}
NON_SERVICE_CORRECTION_WORDS = {
    "오늘",
    "내일",
    "모레",
    "오전",
    "오후",
    "저녁",
    "밤",
    "여기",
    "거기",
}


def _strip_search_term_suffix(value):
    text = str(value or "").strip()
    for suffix in (
        "좀",
        "으로",
        "로",
        "에서",
        "에",
    ):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]
            break
    return text.strip()


def _self_corrected_service_term(request_text):
    _, current = _split_contextual_request(
        request_text
    )
    matches = list(
        SELF_CORRECTION_RE.finditer(
            str(current or "")
        )
    )
    if not matches:
        return None

    match = matches[-1]
    previous = _strip_search_term_suffix(
        match.group(1)
    )
    corrected = _strip_search_term_suffix(
        match.group(2)
    )
    if (
        not previous
        or not corrected
        or corrected in NON_SERVICE_CORRECTION_WORDS
    ):
        return None

    # 행정구역/기준장소 정정은 location 처리 규칙에 맡긴다.
    if corrected.endswith(
        (
            "시",
            "군",
            "구",
            "동",
            "읍",
            "면",
            "리",
            "시청",
            "군청",
            "구청",
            "역",
        )
    ):
        return None

    return previous, corrected


def _food_search_term(value):
    text = str(value or "").strip()
    if text.endswith("집") and len(text) > 2:
        return text[:-1]
    return text


def _apply_spoken_self_correction(
    intent,
    request_text,
):
    if not isinstance(intent, dict):
        return intent
    if intent.get("intent") != "place_search":
        return intent

    correction = _self_corrected_service_term(
        request_text
    )
    if correction is None:
        return intent

    previous, corrected = correction
    result = dict(intent)

    category = _clean_text(
        result.get("category")
    )
    subject = _clean_text(
        result.get("subject")
    )
    corrected_search = _food_search_term(
        corrected
    )

    # "-집"으로 끝나는 음식점 표현이나 이미 식당으로 분류된 요청은
    # 넓은 업종은 식당으로 유지하고 구체 메뉴를 검색어로 분리한다.
    if (
        corrected.endswith("집")
        or category in FOOD_PLACE_TERMS
    ):
        result["category"] = "식당"
        result["subject"] = corrected
        result["search_terms"] = [
            corrected_search
        ]
    else:
        if (
            not category
            or previous in category
            or category in {
                previous,
                subject,
            }
        ):
            result["category"] = corrected
        result["subject"] = corrected
        result["search_terms"] = [corrected]

    result["target_business"] = None

    result["constraints"] = [
        item
        for item in _clean_list(
            result.get("constraints")
        )
        if previous not in item
    ]

    return result


def _apply_proactive_clarification(
    intent,
):
    if not isinstance(intent, dict):
        return intent

    result = dict(intent)

    if result.get("needs_clarification") is True:
        if not _clean_text(
            result.get("clarification_question")
        ):
            result["clarification_question"] = (
                "진행에 필요한 정보를 한 가지만 더 알려주세요."
            )
        return result

    if result.get("intent") != "place_search":
        return result

    location = (
        result.get("location")
        if isinstance(result.get("location"), dict)
        else {}
    )
    location_value = _clean_text(
        location.get("value")
    )
    target_business = _clean_text(
        result.get("target_business")
    )
    category = (
        _clean_text(result.get("category"))
        or _clean_text(result.get("subject"))
    )

    if not target_business and not category:
        result["needs_clarification"] = True
        result["clarification_question"] = (
            "어떤 종류의 업체나 장소를 찾을까요?"
        )
        return result

    if not target_business and not location_value:
        result["needs_clarification"] = True
        result["clarification_question"] = (
            "어느 지역이나 기준 장소 주변에서 찾을까요?"
        )
        return result

    return result


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
        search_terms = (
            list(intent.get("search_terms") or [])
            or [category]
        )

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
    needs_clarification = (
        intent.get("needs_clarification") is True
    )
    clarification_question = (
        _clean_text(
            intent.get("clarification_question")
        )
        or "진행에 필요한 정보를 한 가지만 더 알려주세요."
    )

    mission = {
        "title": goal,
        "summary": goal,
        "category": category,
        "subcategories": [category],
        "intent": "place_search",
        "search_mode": search_mode,
        "response_mode": (
            "clarify"
            if needs_clarification
            else "research"
        ),
        "direct_answer": None,
        "location": location,
        "location_explicit": intent["location"]["explicit"],
        "subject": subject,
        "target_business": target_business,
        "attributes": intent["attributes"],
        "constraints": intent["constraints"],
        "criteria": list(intent.get("criteria") or []),
        "comparison": intent["sort"],
        "search_terms": search_terms,
        "requested_count": requested_count,
        "required_facts": required_facts,
        "needs_fresh_data": True,
        "may_need_phone_call": False,
        "missing_information": (
            [clarification_question]
            if needs_clarification
            else []
        ),
        "clarification_questions": (
            [
                {
                    "question": clarification_question,
                    "options": [],
                }
            ]
            if needs_clarification
            else []
        ),
        "ready_to_research": not needs_clarification,
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
            "criteria": list(intent.get("criteria") or []),
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
        "criteria": list(intent.get("criteria") or []),
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
            "criteria": list(intent.get("criteria") or []),
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
        "criteria": list(intent.get("criteria") or []),
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


def _split_contextual_request(value):
    text = str(value or "").strip()
    marker = "[현재 요청]"
    if marker not in text:
        return {}, text

    context_part, current = text.rsplit(marker, 1)
    current = current.strip()

    start = context_part.find("{")
    if start < 0:
        return {}, current

    decoder = json.JSONDecoder()
    try:
        context, _ = decoder.raw_decode(
            context_part[start:]
        )
    except (json.JSONDecodeError, ValueError):
        return {}, current

    return (
        context if isinstance(context, dict) else {},
        current,
    )


PLACE_CATEGORY_GROUPS = (
    {"치과", "치과의원"},
    {"병원", "의원", "클리닉"},
    {"약국"},
    {"식당", "음식점", "맛집", "레스토랑", "밥집"},
    {"카페", "커피숍"},
    {"미용실", "헤어샵"},
    {"타이어점", "타이어", "정비소", "카센터"},
    {"호텔", "숙박", "모텔"},
    {"학원"},
    {"주차장"},
    {"주유소"},
    {"은행"},
    {"마트"},
    {"편의점"},
    {"부동산"},
)


def _place_category_group(text):
    compact = re.sub(
        r"\s+",
        "",
        str(text or ""),
    )
    for index, group in enumerate(
        PLACE_CATEGORY_GROUPS
    ):
        if any(
            term in compact
            for term in group
        ):
            return index
    return None


def _has_conflicting_place_category(
    current,
    existing_category,
):
    existing_group = _place_category_group(
        existing_category
    )
    if existing_group is None:
        return False

    compact = re.sub(
        r"\s+",
        "",
        str(current or ""),
    )
    current_groups = {
        index
        for index, group in enumerate(
            PLACE_CATEGORY_GROUPS
        )
        if any(
            term in compact
            for term in group
        )
    }
    return bool(
        current_groups
        and existing_group not in current_groups
    )


def _fast_recent_place_comparison(user_request):
    context, current = _split_contextual_request(
        user_request
    )
    recent = context.get("recent_place_results")
    if not isinstance(recent, list) or not recent:
        return None

    compact = re.sub(
        r"\s+",
        "",
        str(current or ""),
    )
    followup_scope = re.search(
        (
            r"그중|그중에서|아까|찾은.*중|이중|이중에서|이곳중|이곳들중|"
            r"여기서|여기중|방금.*(?:곳|업체).*중|"
            r"(?:이|그)?(?:다섯|5)곳중"
        ),
        compact,
    )
    if not followup_scope:
        return None

    if "말고" in compact or "대신" in compact:
        return None

    existing_category = _clean_text(
        context.get("category")
    )
    if _has_conflicting_place_category(
        current,
        existing_category,
    ):
        return None

    criteria = []
    facts = []
    comparison = "criteria_filter"

    def add_fact(value):
        if value not in facts:
            facts.append(value)

    def add_criterion(
        field,
        operator,
        value,
        label,
    ):
        key = (field, operator, str(value))
        if any(
            (
                item.get("field"),
                item.get("operator"),
                str(item.get("value")),
            )
            == key
            for item in criteria
        ):
            return

        criteria.append(
            {
                "id": f"c{len(criteria) + 1}",
                "field": field,
                "operator": operator,
                "value": value,
                "required": True,
                "label": label,
            }
        )

    if re.search(
        r"가장늦|제일늦|늦게까지|늦게하는|늦은",
        compact,
    ):
        comparison = "latest_closing"
        add_fact("영업시간")
        add_criterion(
            "closing_time",
            "max",
            None,
            "가장 늦게 영업",
        )

    if re.search(
        r"주차.*(되는|되고|되며|가능|있고|있는)|주차되는|주차되고|주차가능",
        compact,
    ):
        if comparison == "criteria_filter":
            comparison = "parking_available"
        add_fact("주차")
        add_criterion(
            "parking_available",
            "eq",
            True,
            "주차 가능",
        )

    if re.search(
        r"가장가까|제일가까|가까운",
        compact,
    ):
        if comparison == "criteria_filter":
            comparison = "nearest"
        add_fact("거리")
        add_criterion(
            "distance_m",
            "min",
            None,
            "가장 가까운 곳",
        )

    if re.search(
        r"가장저렴|제일저렴|가장싼|제일싼",
        compact,
    ):
        if comparison == "criteria_filter":
            comparison = "lowest_price"
        add_fact("가격")
        add_criterion(
            "price",
            "min",
            None,
            "가장 저렴한 곳",
        )

    time_match = re.search(
        r"(?:저녁|밤)?(\d{1,2})시(?:이후|넘어서|넘게|까지)",
        compact,
    )
    if time_match:
        hour = int(time_match.group(1))
        if 1 <= hour <= 11:
            hour += 12
        if 0 <= hour <= 23:
            threshold = f"{hour:02d}:00"
            add_fact("영업시간")
            add_criterion(
                "closing_time",
                "gte",
                threshold,
                f"{threshold} 이후까지 영업",
            )

    price_match = re.search(
        r"(\d+(?:\.\d+)?)(만원|만|원)?(?:이하|미만|이내|안쪽)",
        compact,
    )
    if price_match:
        amount = float(price_match.group(1))
        unit = price_match.group(2) or ""
        if unit in {"만원", "만"}:
            amount *= 10000
        if amount.is_integer():
            amount = int(amount)
        add_fact("가격")
        add_criterion(
            "price",
            "lte",
            amount,
            f"{amount:g}원 이하"
            if isinstance(amount, float)
            else f"{amount}원 이하",
        )

    if re.search(
        r"(예약|접수).*(가능|되는)|(가능|되는).*(예약|접수)",
        compact,
    ):
        add_fact("예약 가능 여부")
        add_criterion(
            "availability",
            "eq",
            True,
            "예약 가능",
        )

    if not criteria:
        return None

    category = (
        _clean_text(context.get("category"))
        or "장소"
    )
    location = _clean_text(context.get("location"))

    return {
        "title": current,
        "summary": current,
        "category": category,
        "subcategories": [category],
        "intent": "place_search",
        "search_mode": "comparison",
        "response_mode": "research",
        "direct_answer": None,
        "location": location,
        "location_explicit": False,
        "subject": category,
        "target_business": None,
        "attributes": {
            "reuse_recent_results": True,
        },
        "constraints": [
            item["label"]
            for item in criteria
        ],
        "criteria": criteria,
        "comparison": comparison,
        "search_terms": [category],
        "requested_count": len(recent),
        "required_facts": facts,
        "needs_fresh_data": True,
        "may_need_phone_call": False,
        "missing_information": [],
        "clarification_questions": [],
        "ready_to_research": True,
        "user_goal": current,
        "decision_needed": (
            "직전에 확인한 장소들만 대상으로 모든 필수 조건을 "
            "교집합 판정해서 가장 적합한 곳을 고른다."
        ),
        "known_facts": {
            "recent_result_count": len(recent),
        },
        "unknown_facts": facts,
        "research_plan": [
            {
                "step": 1,
                "goal": (
                    "직전 장소 결과의 필요한 정보만 보강하고 "
                    "업체별 조건 판정표를 만든다."
                ),
                "tool": "recent_place_results",
                "when": "항상",
            }
        ],
        "completion_criteria": [
            "직전 장소 결과 밖의 새 업체를 섞지 않는다.",
            "모든 필수 조건을 업체별로 match/fail/unknown으로 판정한다.",
            "모든 필수 조건이 match인 업체만 확정 추천한다.",
            "근거가 없는 조건은 unknown으로 남기고 추측하지 않는다.",
        ],
        "confidence_target": "high",
        "location_context": {
            "value": location,
            "type": "administrative_area"
            if location
            else "none",
            "radius_hint_km": None,
        },
        "intent_brain": {
            "intent": "place_search",
            "sort": comparison,
            "requested_facts": facts,
            "criteria": criteria,
        },
        "brain_version": "recent-comparison-fast-v2",
    }


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

    fast_comparison = _fast_recent_place_comparison(
        request_text
    )
    if fast_comparison is not None:
        diagnostics["architecture"] = "recent_comparison_fast_v1"
        diagnostics["stage"] = "fast_route_complete"
        diagnostics["route"] = "recent_place_comparison"
        diagnostics["openai_elapsed_ms"] = 0
        return _attach_task_state(fast_comparison)

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
        intent = _apply_spoken_self_correction(
            intent,
            request_text,
        )
        intent = _apply_proactive_clarification(
            intent,
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

    return _attach_task_state(
        _mission_from_intent(intent)
    )
