import json
import os
import re
from time import monotonic

from openai import OpenAI

from .openai_service import get_api_key
from .training_service import active_rules_text
from .intent_brain_service import enhance_mission


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
  "search_mode": "exact_place|category_discovery|area_discovery|follow_up_detail|comparison|general",
  "response_mode": "answer|research|clarify",
  "direct_answer": "현재 대화정보만으로 확실히 답할 수 있을 때의 짧은 답변 또는 null",
  "location": "지역 또는 null",
  "location_explicit": true,
  "subject": "현재 이어지고 있는 핵심 대상",
  "target_business": "사용자가 특정 업체를 지목했으면 정확한 상호명, 아니면 null",
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
  "ready_to_research": true,
  "user_goal": "사용자가 최종적으로 이루려는 현실 목적",
  "decision_needed": "ARABA가 조사 후 내려야 할 판단 또는 실행 결정",
  "expected_answer": {
    "type": "direct_answer|fact_summary|comparison|recommendation|diagnosis_support|decision_support|execution_result|plan",
    "summary": "최종 답변이 어떤 모습이어야 하는지",
    "must_include": ["최종 답에 반드시 들어가야 할 항목"]
  },
  "known_facts": {
    "이미 확인된 핵심 사실": "값"
  },
  "unknown_facts": ["답을 완성하기 위해 아직 확인할 사실"],
  "evidence_needed": [
    {
      "fact": "확인할 사실",
      "source_priority": ["place_search", "web_search", "phone"],
      "required": true
    }
  ],
  "research_plan": [
    {
      "step": 1,
      "goal": "이 단계에서 확인할 것",
      "tool": "direct_reasoning|place_search|map|web_search|records|image|phone",
      "when": "이 도구를 사용할 조건"
    }
  ],
  "completion_criteria": ["조사를 끝내도 되는 조건"],
  "confidence_target": "high|medium|low",
  "location_context": {
    "value": "지역 또는 기준장소",
    "type": "administrative_area|reference_point|none",
    "radius_hint_km": null
  }
}

규칙:
1. 사용자가 말하지 않은 사실을 만들어내지 않는다.
2. category는 고정 목록에서 고르지 말고 실제 요청에 맞게 만든다.
3. subcategories와 attributes도 실제 대화에서 확인된 정보만 만든다.
4. 대화 문맥은 참고자료일 뿐 현재 요청보다 우선하지 않는다.
   먼저 [현재 요청]의 의미와 범위를 독립적으로 해석한 뒤,
   그 해석에 필요한 문맥만 가져온다.
5. 이전에 특정 치과, 식당, 미용실 등 한 업체를 말했더라도
   현재 요청이 "중동 치과 찾아줘", "근처 치과 몇 곳 보여줘",
   "의창구 식당 추천해줘"처럼 업종 전체를 묻는 의미라면
   과거 특정 업체를 target_business로 유지하지 않는다.
6. 반대로 "그 치과 영업시간은?", "아까 그곳 가격은?",
   "거기 예약해줘"처럼 명백한 후속질문일 때만
   직전 target_business를 유지한다.
7. 이미 확인된 정보는 현재 요청의 의미와 충돌하지 않는 범위에서만 재사용한다.
8. "예약 잡아줘", "그곳으로 해줘", "진행해줘"처럼 지시대명사 기반 후속 명령이면 현재 subject/category를 유지한다.
9. 사용자가 명시적으로 새 주제나 새 검색범위를 말하면 즉시 그 현재 요청을 우선한다.
10. 검색, 지도, 업체 전화, 이미지 판독으로 알아낼 수 있는 정보는 사용자에게 묻지 않는다.
11. 예약을 원하는데 희망시간이 없으면 그것 때문에 조사를 멈추지 않는다.
   required_facts에 "업체가 제시 가능한 예약시간대"를 넣고 업체별 가능시간을 조사한 뒤 사용자가 선택하게 한다.
12. 특정 희망시간이 있으면 attributes에 보존하고 그 시간 가능 여부를 required_facts에 포함한다.
13. 추가 질문은 정말 필요한 경우에만 1개 한다.
    다음 정보는 묻지 말고 직접 조사한다:
    - 검색·지도·네이버 플레이스·전화로 확인 가능한 정보
    - 현재 대화 문맥에 이미 있는 정보
    - 결과 후보를 먼저 찾은 뒤 선택할 수 있는 정보
    - 가장 가능성 높은 해석으로 우선 조사해도 사용자의 목적을 해치지 않는 정보
14. 다음 조건을 모두 만족할 때만 역질문한다:
    - 사용자만 답할 수 있는 정보이고
    - 그 정보가 없으면 서로 전혀 다른 결과나 행동으로 갈리며
    - 검색이나 후속 비교로 대신 해결할 수 없다.
15. 단순 확인 질문, 검색 시작 허가, 이미 말한 조건의 재확인은 하지 않는다.
    애매함을 여러 후보로 보여줘 해결할 수 있으면 질문하지 말고 조사한다.
16. search_mode를 현재 요청의 의미로 먼저 결정한다:
    - exact_place: 특정 상호/기관/시설 그 자체를 찾는 요청
    - category_discovery: 특정 지역 안의 치과/식당/미용실 등 업종 후보 전체를 찾는 요청
    - area_discovery: 장소나 명소 등 지역 안의 폭넓은 후보를 찾는 요청
    - follow_up_detail: 이미 선택된 특정 대상의 영업시간/가격/전화/주차/예약 등을 이어서 묻는 요청
    - comparison: 여러 후보를 비교하거나 순위를 원하는 요청
    - general: 업체검색이 아닌 일반 설명/질문
17. category_discovery, area_discovery, comparison 모드에서는
    현재 요청에 특정 상호명이 명시되지 않은 한 target_business=null로 둔다.
    과거 대화의 특정 업체를 자동 승계하면 안 된다.
18. follow_up_detail 모드에서만 현재 요청에 상호명이 없어도
    직전 대화의 target_business를 승계할 수 있다.
19. 역질문이 있으면 ready_to_research=false, 없으면 clarification_questions=[] 및 ready_to_research=true다.
20. 일반적인 업체 탐색에서는 search_terms를 업종/서비스 중심의 짧은 검색어 1~4개로 만든다.
21. [현재 요청]에서 사용자가 특정 상호명, 기관명, 시설명, 학교명, 병원명 등
    고유한 장소 이름을 직접 말하면 단순 "찾아봐" 요청이라도 반드시 target_business에
    그 이름을 그대로 넣고 search_terms 첫 항목에도 정확한 이름을 넣는다.
    예: "의창구청 찾아봐" -> target_business="의창구청".
    이 경우 이전 대화의 업종/category/subcategories가 새 대상을 막아서는 안 된다.
    새 대상에 맞게 category/subcategories를 다시 만들고, 이전 대상의 업종 조건을 버린다.
22. location_explicit은 [현재 요청] 자체에 지역명이 직접 들어 있을 때만 true다.
    대화 문맥에서 물려받은 지역만 있으면 false다.
    새 고유 장소를 직접 지목했는데 현재 요청에 지역을 말하지 않았다면,
    과거의 동/읍/면 같은 세부 지역으로 그 장소를 제한하지 않는다.
23. 사용자가 결과를 요청했으면 과정 설명보다 최종적으로 확인해야 할 사실을 required_facts에 집중한다.
24. response_mode 결정 기준:
    - answer: 현재 대화에서 이미 확인된 사실 또는 외부 조회가 필요 없는 설명만으로 정확히 답할 수 있을 때.
      이때 direct_answer에 실제 답변을 넣고 clarification_questions=[],
      ready_to_research=false로 한다.
    - research: 검색, 지도, 네이버 플레이스, 최신 가격/영업시간/재고/예약 가능 여부,
      실제 업체 정보처럼 외부 확인으로 해결할 수 있을 때.
      이때 질문하지 말고 clarification_questions=[], ready_to_research=true로 한다.
    - clarify: 오직 사용자만 답할 수 있는 필수정보가 없고,
      그 정보 없이는 서로 전혀 다른 결과나 실행으로 갈릴 때만 사용한다.
      이때 질문은 정확히 1개만 만들고 ready_to_research=false로 한다.
25. "찾아볼까요?", "검색해도 될까요?", "어느 정도로 찾아드릴까요?" 같은
    검색 시작 허가나 불필요한 확인 질문은 절대 하지 않는다.
26. 조사 후 사용자의 선택이 필요한 경우에만 결과를 먼저 보여준 뒤 묻는다.
    예: 실제 가능한 예약시간 3개를 확인한 뒤 그중 하나를 선택하게 한다.
27. direct_answer에는 확인되지 않은 외부 사실을 절대 넣지 않는다.
28. 가장 먼저 "사용자가 결국 어떤 답을 받으면 만족하는가"를 판단한다.
    업종, 지역, 상호명은 목표를 해결하기 위한 조건일 뿐 사고의 출발점으로 삼지 않는다.
29. expected_answer에는 실제 조사결과를 미리 지어내지 말고
    최종 답의 구조와 반드시 채워야 할 항목만 설계한다.
30. unknown_facts와 evidence_needed는 expected_answer의 빈칸을 역산해서 만든다.
    사용자가 원하는 답과 관계없는 사실은 조사하지 않는다.
31. research_plan은 필요한 사실마다 가장 적절한 도구를 고른다.
    장소검색이 필요 없는 요청에 place_search를 억지로 넣지 않는다.
    설명만으로 답할 수 있으면 direct_reasoning,
    장소 후보가 필요하면 place_search/map,
    공개 최신정보가 필요하면 web_search,
    기존 조사기록이 중요하면 records,
    사진이나 문서 확인이 필요하면 image,
    검색으로 알 수 없는 현재 가능여부·가격·재고·예약·협의가 필요하면 phone을 사용한다.
32. completion_criteria는 "검색결과를 몇 개 찾았는가"가 아니라
    사용자가 실제로 결정하거나 다음 행동을 할 수 있을 만큼 답이 완성되었는가를 기준으로 만든다.
33. location_context에서 시/군/구/읍/면/동처럼 행정구역 자체가 범위면 administrative_area다.
    "창원시청 주변", "서울역 근처", "OO병원 앞"처럼 특정 장소를 기준으로 주변을 찾는 요청이면
    type=reference_point로 하고 value에는 기준 장소명을 넣는다.
    reference_point를 행정구역 문자열처럼 주소 필터에 사용하면 안 된다.
34. 사용자가 결과를 원하는데 현재 증거가 부족하면 "잘 안 된다"고 끝내지 말고
    research_plan에 검색어 변경, 범위 확장, 다른 출처, 전화 확인 등 다음 조사수단을 설계한다.
35. known_facts에는 현재 요청과 충돌하지 않는 이미 확인된 사실만 넣는다.
36. JSON 이외의 설명, Markdown, 코드블록을 출력하지 않는다.
""".strip()


MISSION_MODEL = (
    os.getenv("ARABA_MISSION_MODEL", "gpt-6-luna").strip()
    or "gpt-6-luna"
)
MISSION_TIMEOUT_SECONDS = 7.0


VALID_SEARCH_MODES = {
    "exact_place",
    "category_discovery",
    "area_discovery",
    "follow_up_detail",
    "comparison",
    "general",
}


def _current_request_text(request_text):
    text = str(request_text or "")
    marker = "[현재 요청]"
    if marker not in text:
        return text.strip()

    current = text.split(
        marker,
        1,
    )[1]

    # 구버전 앱은 [현재 요청] 뒤에 대화 문맥을 붙였고,
    # 신버전은 문맥 뒤 마지막에 현재 요청을 둔다.
    # 어느 순서든 현재 요청 블록만 잘라내야 과거 주제의
    # 상호명/업종이 새 질문의 명시 정보로 오인되지 않는다.
    for boundary in (
        "[대화 문맥 - 참고용]",
        "[대화 문맥]",
        "[판단 규칙]",
    ):
        if boundary in current:
            current = current.split(
                boundary,
                1,
            )[0]

    return current.strip()


def _compact_text(value):
    return re.sub(
        r"[^0-9a-zA-Z가-힣]",
        "",
        str(value or "").lower(),
    )


def _has_follow_up_reference(text):
    compact = _compact_text(text)
    markers = (
        "그곳",
        "거기",
        "그업체",
        "그가게",
        "그치과",
        "그병원",
        "그식당",
        "그미용실",
        "아까",
        "방금",
        "해당업체",
        "해당가게",
    )
    return any(
        marker in compact
        for marker in markers
    )



def _clean_fast_place_subject(value):
    text = " ".join(
        str(value or "").split()
    ).strip(" ?!.,")
    if not text:
        return ""

    text = re.sub(
        r"\s*(?:좀\s*)?(?:알아봐(?:줘)?|찾아봐(?:줘)?|찾아줘|검색해줘|추천해줘|보여줘)\s*$",
        "",
        text,
    ).strip()
    text = re.sub(
        r"\s*(?:몇\s*(?:군데|곳)|여러\s*(?:군데|곳))\s*$",
        "",
        text,
    ).strip()
    text = re.sub(
        r"(?:할\s*만한|괜찮은)\s*곳\s*$",
        "",
        text,
    ).strip()
    text = re.sub(
        r"\s+곳\s*$",
        "",
        text,
    ).strip()
    return text


def _build_fast_place_mission(
    location,
    subject,
    *,
    location_type,
    search_mode,
    radius_hint_km,
):
    location = " ".join(
        str(location or "").split()
    ).strip()
    subject = _clean_fast_place_subject(
        subject
    )

    if (
        len(_compact_text(location)) < 2
        or len(_compact_text(subject)) < 2
    ):
        return None

    if location_type == "reference_point":
        scope_text = f"{location} 주변"
        decision_needed = (
            "기준 장소 주변에서 요청에 맞는 실제 후보를 찾는다."
        )
        first_goal = (
            f"{location} 좌표를 기준으로 {subject} 후보를 찾는다."
        )
    else:
        scope_text = location
        decision_needed = (
            "지정한 행정구역 안에서 요청에 맞는 실제 후보를 찾는다."
        )
        first_goal = (
            f"{location} 범위에서 {subject} 후보를 찾는다."
        )

    summary = (
        f"{scope_text}에서 {subject} 관련 장소를 찾아 비교한다."
    )

    mission = {
        "title": f"{scope_text} {subject} 찾기",
        "summary": summary,
        "category": subject,
        "subcategories": [subject],
        "intent": "조사",
        "search_mode": search_mode,
        "response_mode": "research",
        "direct_answer": None,
        "location": location,
        "location_explicit": True,
        "subject": subject,
        "target_business": None,
        "attributes": {},
        "constraints": [],
        "comparison": "거리와 적합성",
        "search_terms": [subject],
        "required_facts": [
            "후보 장소",
            "주소",
            "전화번호",
            "거리",
        ],
        "needs_fresh_data": True,
        "may_need_phone_call": False,
        "missing_information": [],
        "clarification_questions": [],
        "ready_to_research": True,
        "user_goal": summary,
        "decision_needed": decision_needed,
        "expected_answer": {
            "type": "recommendation",
            "summary": (
                "실제 장소 후보를 카드로 보여주고 위치와 기본 정보를 비교한다."
            ),
            "must_include": [
                "후보 장소",
                "주소",
                "전화번호",
                "거리",
            ],
        },
        "known_facts": {
            "검색 범위": location,
            "찾는 대상": subject,
        },
        "unknown_facts": [
            "실제 후보 장소",
            "주소",
            "전화번호",
            "거리",
        ],
        "evidence_needed": [
            {
                "fact": "실제 후보 장소",
                "source_priority": [
                    "place_search",
                    "map",
                ],
                "required": True,
            },
        ],
        "research_plan": [
            {
                "step": 1,
                "goal": first_goal,
                "tool": "place_search",
                "when": "항상",
            },
            {
                "step": 2,
                "goal": "후보의 위치와 거리를 확인한다.",
                "tool": "map",
                "when": "후보를 찾은 뒤",
            },
        ],
        "completion_criteria": [
            "검색 범위 안의 실제 후보가 확보된다.",
            "후보별 주소와 위치정보를 사용자에게 제시할 수 있다.",
        ],
        "confidence_target": "high",
        "location_context": {
            "value": location,
            "type": location_type,
            "radius_hint_km": radius_hint_km,
        },
    }

    return mission


def _fast_reference_place_mission(request_text):
    """
    'OO 주변/근처에 XX 찾아줘'처럼 의미가 명확한 장소 탐색은
    LLM 왕복 없이 Core 내부의 결정적 파서로 바로 조사 Mission으로 만든다.
    복잡하거나 애매한 요청만 GPT Core 모델로 보낸다.
    """
    current = _current_request_text(
        request_text
    )
    compact = _compact_text(current)

    if not any(
        marker in compact
        for marker in (
            "알아봐",
            "찾아",
            "검색",
            "추천",
            "보여줘",
        )
    ):
        return None

    match = re.match(
        r"^\s*(?P<location>.+?)\s*(?:주변|근처|인근)(?:에|에서)?\s*(?P<subject>.+?)\s*$",
        current,
    )
    if match is None:
        return None

    location = " ".join(
        match.group("location").split()
    ).strip()
    location = re.sub(
        r"^(?:어|음|저기|그러면|그럼)\s+",
        "",
        location,
    ).strip()

    mission = _build_fast_place_mission(
        location,
        match.group("subject"),
        location_type="reference_point",
        search_mode="area_discovery",
        radius_hint_km=3,
    )
    if mission is None:
        return None

    return enhance_mission(
        mission,
        request_text,
    )


_ADMIN_LOCATION_PATTERN = (
    r"(?:[0-9a-zA-Z가-힣]+"
    r"(?:특별자치시|특별자치도|특별시|광역시|도|시|군|구|읍|면|동|리)"
    r"\s*)+"
)


def _fast_administrative_place_mission(request_text):
    """
    '창원시 의창구 중동에 치과 몇 군데 찾아줘'처럼
    행정구역과 찾을 업종이 모두 명확한 요청도 LLM 없이 바로 조사한다.
    """
    current = _current_request_text(
        request_text
    )
    compact = _compact_text(current)

    if not any(
        marker in compact
        for marker in (
            "알아봐",
            "찾아",
            "검색",
            "추천",
            "보여줘",
        )
    ):
        return None

    match = re.match(
        rf"^\s*(?P<location>{_ADMIN_LOCATION_PATTERN})"
        r"(?:에|에서)\s*(?P<subject>.+?)\s*$",
        current,
    )
    if match is None:
        return None

    mission = _build_fast_place_mission(
        match.group("location"),
        match.group("subject"),
        location_type="administrative_area",
        search_mode="category_discovery",
        radius_hint_km=None,
    )
    if mission is None:
        return None

    return enhance_mission(
        mission,
        request_text,
    )

def _normalize_search_scope(
    mission,
    request_text,
):
    current = _current_request_text(
        request_text
    )
    current_compact = _compact_text(current)
    target = str(
        mission.get("target_business") or ""
    ).strip()
    target_compact = _compact_text(target)

    target_is_explicit = bool(
        target_compact
        and target_compact in current_compact
    )
    follow_up_reference = (
        _has_follow_up_reference(current)
    )

    mode = str(
        mission.get("search_mode") or ""
    ).strip()

    if target:
        if target_is_explicit:
            if mode not in {
                "exact_place",
                "follow_up_detail",
            }:
                mission["search_mode"] = (
                    "exact_place"
                )
        elif follow_up_reference:
            mission["search_mode"] = (
                "follow_up_detail"
            )
        else:
            # 현재 질문에 상호가 없고 지시대명사도 없으면
            # 과거의 특정 업체가 새 범위 검색을 가두지 못하게 한다.
            mission["target_business"] = None
            if mode in {
                "",
                "exact_place",
                "follow_up_detail",
                "general",
            }:
                mission["search_mode"] = (
                    "category_discovery"
                )

    if (
        str(
            mission.get("search_mode") or ""
        ).strip()
        not in VALID_SEARCH_MODES
    ):
        if mission.get("target_business"):
            mission["search_mode"] = (
                "exact_place"
            )
        elif (
            mission.get("ready_to_research")
            is True
        ):
            mission["search_mode"] = (
                "category_discovery"
            )
        else:
            mission["search_mode"] = (
                "general"
            )

    return mission


def _force_place_research_when_clear(
    mission,
    request_text,
):
    current = _current_request_text(
        request_text
    )
    compact = _compact_text(current)

    place_markers = (
        "찾아줘",
        "찾아봐",
        "알아봐",
        "추천",
        "근처",
        "주변",
        "몇곳",
        "몇군데",
    )
    wants_place_result = any(
        marker in compact
        for marker in place_markers
    )

    has_search_target = bool(
        str(
            mission.get("target_business") or ""
        ).strip()
        or str(
            mission.get("location") or ""
        ).strip()
        or (
            isinstance(
                mission.get("search_terms"),
                list,
            )
            and any(
                str(item).strip()
                for item in mission["search_terms"]
            )
        )
    )

    if not (
        wants_place_result
        and has_search_target
    ):
        return mission

    mission["response_mode"] = "research"
    mission["ready_to_research"] = True

    if (
        not mission.get("target_business")
        and str(
            mission.get("search_mode") or ""
        ).strip()
        in {"", "general", "follow_up_detail"}
    ):
        mission["search_mode"] = (
            "category_discovery"
        )

    # 위치나 검색대상이 이미 있으면 검색으로 확인 가능한 내용을
    # 다시 사용자에게 묻지 않고 바로 조사한다.
    if str(
        mission.get("location") or ""
    ).strip() or mission.get("target_business"):
        mission["clarification_questions"] = []
        mission["missing_information"] = []

    return mission


def _parse_mission_json(raw):
    text = str(raw or "").strip()

    if text.startswith("```"):
        text = (
            text.removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise

        value = json.loads(
            text[start : end + 1]
        )

    if not isinstance(value, dict):
        raise ValueError(
            "Mission 응답이 객체 형식이 아닙니다."
        )

    return value


def _create_mission_response(
    client,
    *,
    instructions,
    request_text,
):
    # 사용자 한 요청에 대해 Core 호출은 한 번만 수행한다.
    # 짧은 타임아웃 뒤 동일 요청을 즉시 다시 호출하면 전체 응답시간만
    # 길어지고 모바일 제한시간과 충돌하므로 중복 재시도를 하지 않는다.
    return client.responses.create(
        model=MISSION_MODEL,
        instructions=instructions,
        input=request_text,
    )


def create_mission(user_request, api_key=None, *, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics["stage"] = "request_validation"
    request_text = str(user_request).strip()

    if not request_text:
        raise ValueError("알아볼 내용을 입력해주세요.")

    api_key = get_api_key(api_key)

    if not api_key:
        raise ValueError(
            "OpenAI API Key가 설정되지 않았습니다."
        )

    diagnostics["stage"] = "fast_route_check"
    fast_routes = (
        (
            "reference_place",
            _fast_reference_place_mission,
        ),
        (
            "administrative_place",
            _fast_administrative_place_mission,
        ),
    )

    for route_name, route_builder in fast_routes:
        fast_mission = route_builder(
            request_text
        )
        if fast_mission is None:
            continue

        diagnostics["fast_path"] = True
        diagnostics["route"] = route_name
        diagnostics["openai_elapsed_ms"] = 0
        diagnostics["stage"] = "fast_route_complete"
        return fast_mission

    diagnostics["fast_path"] = False

    client = OpenAI(
        api_key=api_key,
        timeout=MISSION_TIMEOUT_SECONDS,
        max_retries=0,
    )

    diagnostics["stage"] = "load_rules"
    learned_rules = active_rules_text(
        limit=30,
    )
    instructions = MISSION_SYSTEM_PROMPT

    if learned_rules:
        instructions += (
            "\n\n관리자가 누적시킨 재발방지 학습규칙:\n"
            + learned_rules
        )

    diagnostics["stage"] = "openai_request"
    call_started = monotonic()
    try:
        response = _create_mission_response(
            client,
            instructions=instructions,
            request_text=request_text,
        )
    finally:
        diagnostics["openai_elapsed_ms"] = round(
            (monotonic() - call_started) * 1000
        )

    diagnostics["stage"] = "parse_response"
    raw = response.output_text.strip()

    try:
        mission = _parse_mission_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            "OpenAI가 Mission JSON을 올바르게 반환하지 않았습니다."
        ) from exc

    diagnostics["stage"] = "validate_response"
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
    mission.setdefault("target_business", None)
    mission.setdefault("location_explicit", False)
    mission.setdefault("search_mode", "")
    mission.setdefault("intent", "조사")
    mission.setdefault(
        "response_mode",
        (
            "research"
            if mission.get("ready_to_research") is True
            else (
                "clarify"
                if mission.get("clarification_questions")
                else "answer"
            )
        ),
    )
    mission.setdefault("direct_answer", None)
    mission.setdefault("attributes", {})
    mission.setdefault("search_terms", [])

    if not isinstance(mission["subcategories"], list):
        mission["subcategories"] = []

    if not isinstance(mission["attributes"], dict):
        mission["attributes"] = {}

    if not isinstance(mission["search_terms"], list):
        mission["search_terms"] = []

    diagnostics["stage"] = "normalize_mission"
    mission = _normalize_search_scope(
        mission,
        request_text,
    )

    mission = _force_place_research_when_clear(
        mission,
        request_text,
    )

    mission = enhance_mission(
        mission,
        request_text,
    )

    return mission
