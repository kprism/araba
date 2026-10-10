import json
import os
import re
from time import monotonic

from openai import OpenAI

from .intent_brain_service import enhance_mission
from .execution_planner_service import build_execution_plan
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
   자정을 넘겨 영업하는 시간은 다음 날 시간으로 정규화한다.
   예: "새벽 2시까지" -> closing_time gte "26:00".
   "새벽까지 하는 곳" -> closing_time gte "24:00".
   데이터로 판정할 수 없는 주관 조건은 field="custom"으로 남기고 추측하지 않는다.
4. 시/군/구/읍/면/동 같은 행정구역 자체가 범위면 administrative_area다.
   "창원시청 주변", "서울역 근처"처럼 특정 장소를 기준으로 찾으면 reference_point다.
5. 사용자가 특정 상호나 시설 하나를 직접 지목하면 target_business에 정확히 넣는다.
6. 직전에 보여준 장소의 영업시간, 전화, 주소, 가격, 주차 등 세부정보를 묻는 요청은 place_detail다.
7. 사용자가 숫자로 개수를 말하면 count에 그대로 넣는다. 말하지 않으면 null이다.
8. 일반 지식 질문처럼 외부 최신조회가 필요 없으면 general_answer이고 direct_answer에 짧고 정확한 답을 넣는다.
9. 최신 공개정보 조사가 필요하지만 장소검색이 아니면 web_research다.
10. 전화, 예약, 문의 실행이면 phone_action다.
11. 목표는 이해했지만 그 목표를 제대로 실행하려면 사용자만 알 수 있는 중요한 정보가 빠져 있으면 기다리지 말고 적극적으로 묻는다. 검색으로 알아낼 수 있는 사실은 사용자에게 묻지 않는다. 결과를 크게 바꾸거나 실제 실행에 꼭 필요한 정보만 묻는다.
    필요한 정보가 여러 개라면 한 가지씩 여러 턴에 걸쳐 묻지 말고, 현재 시점에 필요한 항목을 한 번의 자연스러운 질문에 모두 묶어서 묻는다.
    예: "치과 찾아줘"인데 지역이 전혀 없으면 "어느 지역이나 기준 장소 주변에서 찾을까요?"라고 묻는다.
    예: 예약이 목표이고 지역·날짜·시간·인원이 모두 실제 예약에 꼭 필요하며 아직 없다면 "어느 지역에서, 언제 몇 시쯤, 몇 분이 예약하실까요?"처럼 한 번에 묻는다.
    사용자의 답은 새 요청으로 취급하지 말고 기존 goal의 빈칸들을 한꺼번에 채운다. 이미 답한 정보는 다시 묻지 않는다. 선택사항이나 ARABA가 직접 조사할 수 있는 정보는 질문에 끼워 넣지 않는다.
12. 현재 요청이 새 지역·새 업종을 명시하면 과거 업종이나 상호를 승계하지 않는다.
13. [대화 문맥]의 recent_place_results 또는 recent_place_searches에
    직전 장소검색 결과가 있으면 "첫 번째", "두 번째", "그곳", "거기",
    "아까 치과", "아까 미용실" 같은 후속표현을 해당 결과의 실제 상호명으로 해석한다.
    특정 순번이나 한 업체의 주소·전화·영업시간·주차·가격 등을 묻는 경우
    intent=place_detail로 하고 target_business에는 문맥에 있는 정확한 상호명을 넣는다.
    또한 직전 장소 결과 직후 사용자가 새 지역·새 업종을 제시하지 않고
    "토요일에도 가능?", "주차되는 곳?", "8시까지 하는 데?", "가장 싼 곳?"
    처럼 조건을 추가하면 새 업체검색이 아니라 직전 결과 집합을 그대로 대상으로 삼는다.
    이 경우 attributes.reuse_recent_results=true로 두고, 새 조건만 필요한 사실을 조사한다.
    사용자가 "다른 곳", "새로 찾아", "더 찾아", "범위를 넓혀"라고 명시한 경우에만
    직전 결과 범위를 벗어나 새 후보를 찾는다.
14. 사용자가 새 업종을 말하면 recent_place_results의 직전 업종에 끌려가지 않는다.
15. "거기 아니고 X", "X 말고 Y", "지역은 Y야", "아니, Y에서"처럼 사용자가 장소나 지역을 정정하면 이전 위치를 폐기하고 정정한 위치를 현재 요청의 location으로 사용한다. 정정된 위치는 explicit=true로 처리하고, 직전 검색 결과를 재사용하지 말고 새 위치에서 다시 조사한다.
16. 한 발화 안에서 사용자가 말을 고친 경우 마지막 정정이 최종 의도다. "쌈밥이 아니고 국밥집"이면 쌈밥은 완전히 버리고 category="식당", subject="국밥집", search_terms=["국밥"]처럼 구조화한다. "치과 말고 피부과"면 치과를 버리고 피부과만 남긴다. 부정되거나 취소된 단어를 category, subject, search_terms, constraints에 남기지 않는다.
17. 음식 종류처럼 기본 업종보다 구체적인 검색어가 있으면 category에는 넓은 업종(예: 식당)을 두고 search_terms에는 실제 찾을 말(예: 국밥, 냉면, 초밥)을 넣는다.
18. 입력 안에 "사용자 추가 답변:"이 있으면 그것은 새 요청이 아니라 바로 앞에서 ARABA가 부족한 정보를 물은 것에 대한 답이다. 기존 goal을 유지한 채 그 답으로 빈칸을 채우고 다시 판단한다.
19. JSON 이외의 설명, Markdown, 코드블록을 출력하지 않는다.
""".strip()


INTENT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "place_search",
                "place_detail",
                "general_answer",
                "web_research",
                "phone_action",
                "image_analysis",
                "document_analysis",
                "conversation",
                "clarify",
            ],
        },
        "goal": {"type": "string"},
        "location": {
            "type": "object",
            "properties": {
                "value": {
                    "type": ["string", "null"],
                },
                "type": {
                    "type": "string",
                    "enum": [
                        "administrative_area",
                        "reference_point",
                        "none",
                    ],
                },
                "explicit": {"type": "boolean"},
            },
            "required": [
                "value",
                "type",
                "explicit",
            ],
            "additionalProperties": False,
        },
        "category": {
            "type": ["string", "null"],
        },
        "subject": {
            "type": ["string", "null"],
        },
        "search_terms": {
            "type": "array",
            "items": {"type": "string"},
        },
        "target_business": {
            "type": ["string", "null"],
        },
        "count": {
            "type": ["integer", "null"],
            "minimum": 1,
            "maximum": 10,
        },
        "constraints": {
            "type": "array",
            "items": {"type": "string"},
        },
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "enum": [
                            "parking_available",
                            "closing_time",
                            "opening_time",
                            "opening_day",
                            "price",
                            "distance_m",
                            "availability",
                            "stock",
                            "service",
                            "rating",
                            "custom",
                        ],
                    },
                    "operator": {
                        "type": "string",
                        "enum": [
                            "eq",
                            "contains",
                            "gte",
                            "lte",
                            "min",
                            "max",
                            "exists",
                        ],
                    },
                    "value": {
                        "type": [
                            "string",
                            "number",
                            "boolean",
                            "null",
                        ],
                    },
                    "required": {"type": "boolean"},
                    "label": {"type": "string"},
                },
                "required": [
                    "field",
                    "operator",
                    "value",
                    "required",
                    "label",
                ],
                "additionalProperties": False,
            },
        },
        "attributes": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "requested_facts": {
            "type": "array",
            "items": {"type": "string"},
        },
        "sort": {
            "type": "string",
            "enum": [
                "relevance",
                "distance",
                "rating",
                "price",
                "none",
            ],
        },
        "needs_fresh_data": {"type": "boolean"},
        "needs_clarification": {"type": "boolean"},
        "clarification_question": {
            "type": ["string", "null"],
        },
        "direct_answer": {
            "type": ["string", "null"],
        },
    },
    "required": [
        "intent",
        "goal",
        "location",
        "category",
        "subject",
        "search_terms",
        "target_business",
        "count",
        "constraints",
        "criteria",
        "attributes",
        "requested_facts",
        "sort",
        "needs_fresh_data",
        "needs_clarification",
        "clarification_question",
        "direct_answer",
    ],
    "additionalProperties": False,
}


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
    mission["execution_plan"] = build_execution_plan(
        mission
    )
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

STRICT_FOOD_TERMS = {
    "피자",
    "치킨",
    "햄버거",
    "버거",
    "초밥",
    "스시",
    "파스타",
    "족발",
    "보쌈",
    "곱창",
    "막창",
    "떡볶이",
    "샌드위치",
    "베이커리",
    "빵",
}

GENERIC_FOOD_REQUEST_TERMS = {
    "맛집",
    "밥집",
    "음식점",
    "식당",
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


def _explicit_specific_food_term(
    request_text,
):
    _, current = _split_contextual_request(
        request_text
    )
    compact = re.sub(
        r"\s+",
        "",
        str(current or ""),
    )

    for term in sorted(
        STRICT_FOOD_TERMS,
        key=len,
        reverse=True,
    ):
        if term in compact:
            return term

    matches = re.findall(
        r"([가-힣A-Za-z]{2,12})집",
        compact,
    )
    for raw in reversed(matches):
        term = raw.strip()
        if (
            term
            and term not in GENERIC_FOOD_REQUEST_TERMS
        ):
            return term

    return None


def _apply_explicit_specific_food_term(
    intent,
    request_text,
):
    if not isinstance(intent, dict):
        return intent
    if intent.get("intent") != "place_search":
        return intent

    category = _clean_text(
        intent.get("category")
    )
    subject = _clean_text(
        intent.get("subject")
    )
    combined = " ".join(
        value
        for value in (category, subject)
        if value
    )
    if (
        category not in FOOD_PLACE_TERMS
        and not any(
            marker in combined
            for marker in FOOD_PLACE_TERMS
        )
    ):
        return intent

    term = _explicit_specific_food_term(
        request_text
    )
    if not term:
        return intent

    result = dict(intent)
    result["category"] = "식당"
    result["subject"] = (
        subject
        if subject and term in subject
        else f"{term}집"
    )
    result["search_terms"] = [term]
    result["target_business"] = None
    return result


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


CURRENT_LOCATION_PATTERN = re.compile(
    (
        r"내(?:가)?(?:있는|있는곳|위치|주변|근처)|"
        r"현재위치|현위치|내위치|"
        r"여기(?:주변|근처)|"
        r"지금있는곳|지금여기|"
        r"가까운곳|가까운업체|가까운가게"
    )
)


def _valid_device_context(value):
    if not isinstance(value, dict):
        return None
    try:
        latitude = float(value.get("latitude"))
        longitude = float(value.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90):
        return None
    if not (-180 <= longitude <= 180):
        return None

    result = {
        "latitude": latitude,
        "longitude": longitude,
        "source": "device",
    }
    accuracy = value.get("accuracy_m")
    if isinstance(accuracy, (int, float)):
        result["accuracy_m"] = float(accuracy)
    captured_at = str(
        value.get("captured_at") or ""
    ).strip()
    if captured_at:
        result["captured_at"] = captured_at[:80]
    return result


def _requests_current_location(
    request_text,
):
    context, current = _split_contextual_request(
        request_text
    )
    compact = re.sub(
        r"\s+",
        "",
        str(current or ""),
    )

    recent = context.get("recent_place_results")
    if (
        isinstance(recent, list)
        and recent
        and re.search(
            r"그중|이중|여기서|아까|방금찾은",
            compact,
        )
    ):
        return False

    return bool(
        CURRENT_LOCATION_PATTERN.search(compact)
    )


def _apply_device_location_to_intent(
    intent,
    request_text,
    device_context,
):
    if not isinstance(intent, dict):
        return intent
    if intent.get("intent") != "place_search":
        return intent
    if not _requests_current_location(
        request_text
    ):
        return intent

    device = _valid_device_context(
        device_context
    )
    if device is None:
        result = dict(intent)
        location = result.get("location")
        explicit_location = (
            isinstance(location, dict)
            and location.get("explicit") is True
            and _clean_text(location.get("value"))
        )
        if explicit_location:
            return result
        result["needs_clarification"] = True
        result["clarification_question"] = (
            "현재 위치를 기준으로 찾으려면 위치 권한이 필요해요. "
            "위치 권한을 허용하거나 지역·기준 장소를 말씀해주세요."
        )
        return result

    result = dict(intent)
    result["location"] = {
        "value": "현재 위치",
        "type": "reference_point",
        "explicit": False,
    }
    attributes = result.get("attributes")
    attributes = (
        dict(attributes)
        if isinstance(attributes, dict)
        else {}
    )
    attributes["use_device_location"] = True
    result["attributes"] = attributes
    result["needs_clarification"] = False
    result["clarification_question"] = None
    return result


def _apply_device_context_to_mission(
    mission,
    request_text,
    device_context,
):
    if not isinstance(mission, dict):
        return mission
    if not _requests_current_location(
        request_text
    ):
        return mission

    device = _valid_device_context(
        device_context
    )
    if device is None:
        return mission

    result = dict(mission)
    result["location"] = "현재 위치"
    result["location_explicit"] = False
    result["location_context"] = {
        "value": "현재 위치",
        "type": "device_location",
        "latitude": device["latitude"],
        "longitude": device["longitude"],
        "accuracy_m": device.get("accuracy_m"),
        "captured_at": device.get("captured_at"),
        "radius_hint_km": 3,
        "source": "device",
    }
    result["ready_to_research"] = True
    result["response_mode"] = "research"
    result["missing_information"] = []
    result["clarification_questions"] = []
    known = result.get("known_facts")
    known = (
        dict(known)
        if isinstance(known, dict)
        else {}
    )
    known["location_source"] = "device"
    result["known_facts"] = known
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
                "진행에 필요한 정보를 알려주세요."
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

    if not target_business and not category and not location_value:
        result["needs_clarification"] = True
        result["clarification_question"] = (
            "찾으려는 업체·장소 종류와 지역 또는 기준 장소를 함께 알려주세요."
        )
        return result

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
        max_output_tokens=900,
        text={
            "format": {
                "type": "json_schema",
                "name": "araba_intent",
                "schema": INTENT_OUTPUT_SCHEMA,
                "strict": True,
            }
        },
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
        or "진행에 필요한 정보를 알려주세요."
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
            or "진행에 꼭 필요한 정보를 알려주세요."
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


def _fallback_place_intent_from_request(
    request_text,
):
    context, current = _split_contextual_request(
        request_text
    )
    current_text = str(current or "").strip()
    if not current_text:
        return None

    admin_tokens = []
    admin_suffixes = (
        "특별시",
        "광역시",
        "특별자치시",
        "특별자치도",
        "도",
        "시",
        "군",
        "구",
        "읍",
        "면",
        "동",
        "리",
    )
    spoken_endings = (
        "이에요",
        "예요",
        "입니다",
        "이야",
        "이고",
        "에서",
        "으로",
        "은",
        "는",
        "이",
        "가",
        "에",
        "로",
    )
    for raw_token in re.findall(
        r"[가-힣]+",
        current_text,
    ):
        token = raw_token
        for ending in spoken_endings:
            if (
                token.endswith(ending)
                and len(token) > len(ending) + 1
            ):
                token = token[: -len(ending)]
                break
        if token.endswith(admin_suffixes):
            admin_tokens.append(token)
    new_location = " ".join(
        admin_tokens[:5]
    ).strip()

    context_location = str(
        context.get("location") or ""
    ).strip()
    location = new_location or context_location

    category = str(
        context.get("category") or ""
    ).strip()
    subject = str(
        context.get("subject") or ""
    ).strip()

    raw_terms = context.get("search_terms")
    search_terms = (
        [
            str(item).strip()
            for item in raw_terms
            if str(item).strip()
        ]
        if isinstance(raw_terms, list)
        else []
    )

    explicit_food = re.search(
        (
            r"([가-힣A-Za-z0-9]{2,20}집)"
            r"(?:을|를|은|는)?"
            r".{0,12}"
            r"(?:알려|찾아|추천|검색)"
        ),
        current_text,
    )
    if explicit_food:
        subject = explicit_food.group(1)
        category = "식당"
        base = subject[:-1].strip()
        search_terms = [base or subject]
    elif (
        category == "식당"
        and subject.endswith("집")
        and not search_terms
    ):
        base = subject[:-1].strip()
        search_terms = [base or subject]

    search_signal = bool(
        re.search(
            r"찾아|알려|추천|검색|어디|근처|주변",
            current_text,
        )
    )
    correction_signal = bool(
        new_location
        and isinstance(context, dict)
        and (
            context.get("category")
            or context.get("subject")
        )
    )

    if not (
        (location and (category or subject))
        and (search_signal or correction_signal)
    ):
        return None

    if not category:
        category = subject
    if not subject:
        subject = category
    if not search_terms and subject:
        search_terms = [subject]

    raw_count = (
        context.get("requested_count")
        if isinstance(context, dict)
        else None
    )
    try:
        count = (
            int(raw_count)
            if raw_count is not None
            else None
        )
    except (TypeError, ValueError):
        count = None

    return {
        "intent": "place_search",
        "goal": current_text,
        "location": {
            "value": location or None,
            "type": (
                "administrative_area"
                if location
                else "none"
            ),
            "explicit": bool(new_location),
        },
        "category": category or None,
        "subject": subject or None,
        "search_terms": search_terms[:6],
        "target_business": None,
        "count": count,
        "constraints": [],
        "criteria": [],
        "attributes": {},
        "requested_facts": [],
        "sort": "relevance",
        "needs_fresh_data": True,
        "needs_clarification": False,
        "clarification_question": None,
        "direct_answer": None,
    }


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


DAY_NAMES = (
    "월요일",
    "화요일",
    "수요일",
    "목요일",
    "금요일",
    "토요일",
    "일요일",
)


def _explicit_new_location_in_followup(
    current,
    existing_location,
):
    text = str(current or "").strip()
    compact = re.sub(r"\s+", "", text)
    existing = re.sub(
        r"\s+",
        "",
        str(existing_location or ""),
    )

    candidates = re.findall(
        (
            r"([가-힣]{2,}(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구|동|읍|면|리))"
            r"(?=에서|에|근처|주변|쪽)"
        ),
        compact,
    )
    simple_city = re.search(
        (
            r"(서울|부산|대구|인천|광주|대전|울산|세종|제주|수원|창원)"
            r"(?=에서|에|근처|주변|쪽)"
        ),
        compact,
    )
    if simple_city:
        candidates.append(simple_city.group(1))

    return any(
        candidate
        and candidate not in existing
        for candidate in candidates
    )


def _explicit_scope_expansion(current):
    compact = re.sub(
        r"\s+",
        "",
        str(current or ""),
    )
    return bool(
        re.search(
            (
                r"다른곳|다른업체|새로찾|새로운곳|추가로찾|더찾아|"
                r"더찾아봐|범위.*넓|후보.*추가|다른데도"
            ),
            compact,
        )
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

    if (
        "말고" in compact
        or "대신" in compact
        or _explicit_scope_expansion(current)
    ):
        return None

    existing_category = _clean_text(
        context.get("category")
    )
    if _has_conflicting_place_category(
        current,
        existing_category,
    ):
        return None

    existing_location = _clean_text(
        context.get("location")
    )
    if _explicit_new_location_in_followup(
        current,
        existing_location,
    ):
        return None

    criteria = []
    facts = []
    comparison = "criteria_filter"

    previous_criteria = context.get("criteria")
    if isinstance(previous_criteria, list):
        for item in previous_criteria:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip()
            operator = str(item.get("operator") or "eq").strip()
            if not field:
                continue
            criteria.append(
                {
                    "id": f"c{len(criteria) + 1}",
                    "field": field,
                    "operator": operator,
                    "value": item.get("value"),
                    "required": item.get("required") is not False,
                    "label": (
                        str(item.get("label") or field).strip()
                        or field
                    ),
                }
            )

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

    day_match = re.search(
        r"(월요일|화요일|수요일|목요일|금요일|토요일|일요일)",
        compact,
    )
    if day_match:
        target_day = day_match.group(1)
        add_fact("영업시간")
        add_criterion(
            "opening_day",
            "eq",
            target_day,
            f"{target_day} 영업",
        )

    time_match = re.search(
        r"(새벽|오전|낮|오후|저녁|밤)?"
        r"(\d{1,2})시(?:이후|넘어서|넘게|까지)",
        compact,
    )
    if time_match:
        daypart = time_match.group(1) or ""
        hour = int(time_match.group(2))

        if daypart == "새벽":
            if 0 <= hour <= 11:
                hour += 24
        elif daypart in {"오후", "저녁", "밤"}:
            if 1 <= hour <= 11:
                hour += 12
        elif not daypart and 1 <= hour <= 11:
            hour += 12

        if 0 <= hour <= 35:
            threshold = f"{hour:02d}:00"
            display_hour = (
                f"새벽 {hour - 24}시"
                if hour >= 24
                else f"{hour:02d}:00"
            )
            add_fact("영업시간")
            add_criterion(
                "closing_time",
                "gte",
                threshold,
                f"{display_hour} 이후까지 영업",
            )

    if (
        "새벽까지" in compact
        and not any(
            item.get("field") == "closing_time"
            for item in criteria
        )
    ):
        add_fact("영업시간")
        add_criterion(
            "closing_time",
            "gte",
            "24:00",
            "자정을 넘어 새벽까지 영업",
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

    if re.search(
        (
            r"(?:지금|현재|오늘)?(?:주문|배달|포장)"
            r".*(?:가능|되는|돼|되나|받는|받아|할수)|"
            r"(?:가능|되는|돼|되나).*(?:주문|배달|포장)"
        ),
        compact,
    ):
        add_fact("현재 주문 가능 여부")
        add_criterion(
            "availability",
            "eq",
            True,
            "현재 주문 가능",
        )

    if not criteria:
        return None

    # 명시적으로 "그중"이라고 하지 않아도 직전 결과 직후 새 조건만
    # 덧붙인 경우에는 같은 후보 집합의 후속 판정으로 본다.
    if not followup_scope:
        newly_added_count = len(criteria) - (
            len(previous_criteria)
            if isinstance(previous_criteria, list)
            else 0
        )
        if newly_added_count <= 0:
            return None

    category = (
        _clean_text(context.get("category"))
        or "장소"
    )
    location = _clean_text(context.get("location"))
    single_recent = (
        recent[0]
        if len(recent) == 1
        and isinstance(recent[0], dict)
        else None
    )
    single_name = (
        _clean_text(single_recent.get("name"))
        if single_recent
        else None
    )

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
        "subject": single_name or category,
        "target_business": single_name,
        "attributes": {
            "reuse_recent_results": True,
            "reuse_recent_business_only": bool(single_name),
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
            "직전에 확인한 한 업체의 현재 조건만 확인한다."
            if single_name
            else (
                "직전에 확인한 장소들만 대상으로 모든 필수 조건을 "
                "교집합 판정해서 가장 적합한 곳을 고른다."
            )
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
        "brain_version": "recent-comparison-fast-v3",
    }



INDEPENDENT_PLACE_PATTERN = re.compile(
    r"치과|피자집|빵집|베이커리|제과점|식당|음식점|맛집|"
    r"카페|커피숍|병원|약국|학원|미용실|주차장|"
    r"타이어|정비소|꽃집|호텔|펜션|주유소|헬스장"
)
INDEPENDENT_ACTION_PATTERN = re.compile(
    r"찾아|알려|조사|추천|몇\s*곳|어디|확인해|검색"
)


def split_independent_requests(request_text):
    """Split explicit standalone tasks, never split conjunctive criteria."""
    context, current = _split_contextual_request(request_text)
    if not current:
        return [request_text]
    parts = [
        text.strip(" \t,.!?")
        for text in re.split(
            r"\s*(?:[,，]\s*|[.!?]\s*|"
            r"그리고\s+|또한\s+|마지막으로\s+)",
            current,
        )
        if text.strip(" \t,.!?")
    ]
    if not (2 <= len(parts) <= 5):
        return [request_text]
    valid = all(
        INDEPENDENT_PLACE_PATTERN.search(part)
        and INDEPENDENT_ACTION_PATTERN.search(part)
        for part in parts
    )
    if not valid:
        return [request_text]
    if not context:
        return parts
    # Preserve context as optional reference, not as a task to execute.
    marker = "[현재 요청]"
    prefix = str(request_text).rsplit(marker, 1)[0]
    return [
        f"{prefix}{marker}\n{part}"
        for part in parts
    ]


def create_mission(
    user_request,
    api_key=None,
    *,
    diagnostics=None,
    device_context=None,
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
    except (
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        fallback = _fallback_place_intent_from_request(
            request_text
        )
        if fallback is None:
            raise ValueError(
                "OpenAI가 Intent JSON을 올바르게 반환하지 않았습니다."
            ) from exc
        diagnostics["architecture"] = (
            "intent_router_v2+deterministic_place_fallback"
        )
        diagnostics["fallback_used"] = True
        diagnostics["fallback_stage"] = "parse_intent"
        intent = _normalize_intent(
            fallback
        )

    intent = _apply_spoken_self_correction(
        intent,
        request_text,
    )
    intent = _apply_explicit_specific_food_term(
        intent,
        request_text,
    )
    intent = _apply_device_location_to_intent(
        intent,
        request_text,
        device_context,
    )
    intent = _apply_proactive_clarification(
        intent,
    )

    diagnostics["stage"] = "route_intent"
    diagnostics["route"] = intent["intent"]

    mission = _mission_from_intent(intent)
    mission = _apply_device_context_to_mission(
        mission,
        request_text,
        device_context,
    )
    return _attach_task_state(
        mission
    )
