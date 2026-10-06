import hashlib
import json

from openai import OpenAI

from api.models import ResearchRecord, TrainingRule, TrainingRun, TrainingScenario

from .openai_service import get_api_key


AUTO_SCENARIO_AXES = [
    ("예약시간 미정", "사용자가 시간을 정하지 않았으면 업체가 제시하는 가능시간대를 수집한다."),
    ("이미 말한 정보 재질문", "이미 확인한 수량·모델·지역·조건을 다시 묻지 않는다."),
    ("추가비용 뒤늦게 고지", "최종금액 전에 추가비용·필수옵션·결제조건을 확인한다."),
    ("모호한 업체 답변", "모호한 답은 수치·시간·가능여부로 좁혀 다시 확인한다."),
    ("최저가와 시간 충돌", "가격뿐 아니라 왕복거리·대기·처리시간을 함께 비교한다."),
    ("업체의 다른 상품 유도", "사용자 목표와 무관한 판매 유도에 끌려가지 않는다."),
    ("재고·가능시간 변경", "변경된 최신 조건을 반영하고 이전 답을 확정정보처럼 쓰지 않는다."),
    ("취소·변경 조건 중요", "예약 확정 전에 취소·변경·환불·보증 조건을 확인한다."),
    ("통화가 길어짐", "핵심 질문만 남기고 중복 질문을 줄인다."),
    ("주제 이탈 유혹", "사용자가 바꾸지 않은 업종이나 대상은 먼저 꺼내지 않는다."),
]


CORE_CURRICULUM = [
    {
        "key": "historical_reference_point",
        "group": "historical_failure",
        "title": "과거실패 · 기준장소 주변 검색",
        "request": "창원시청 주변에 타이어 교체할 만한 곳 알아봐",
        "goal": "창원시청을 행정구역이 아니라 기준장소로 이해하고 좌표 중심으로 주변 후보를 찾는다.",
        "difficulty": "보통",
        "expected_behaviors": [
            "기준장소를 reference_point로 분류한다.",
            "기준장소명을 업체 주소 문자열 필터로 사용하지 않는다.",
            "좌표와 반경을 이용해 주변 후보를 찾는다.",
        ],
        "rule": {
            "trigger": "사용자가 특정 건물·기관·역·시설의 '주변/근처'를 기준으로 후보를 찾는다.",
            "instruction": "해당 장소를 행정구역으로 해석하지 말고 기준점 좌표를 확보한 뒤 거리·반경 중심으로 조사한다.",
            "example": "창원시청 주변 타이어점 -> 창원시청 좌표 기준 주변 검색",
        },
    },
    {
        "key": "historical_narrow_subcategory",
        "group": "historical_failure",
        "title": "과거실패 · 세부조건이 기본업종을 가림",
        "request": "임플란트 가능한 치과 찾아줘",
        "goal": "임플란트라는 세부조건 때문에 정상 치과 후보 전체를 탈락시키지 않는다.",
        "difficulty": "보통",
        "expected_behaviors": [
            "기본 업종인 치과를 먼저 넓게 찾는다.",
            "임플란트 가능 여부는 후보를 찾은 뒤 검증한다.",
            "세부 서비스 단어가 상호나 지도 카테고리에 없다고 정상 업체를 제거하지 않는다.",
        ],
        "rule": {
            "trigger": "사용자 요청에 기본 업종과 세부 서비스 조건이 함께 있다.",
            "instruction": "기본 업종 후보를 먼저 확보하고 세부 서비스 조건은 후속 검증 항목으로 다룬다. 세부조건 문자열 불일치만으로 정상 후보를 제거하지 않는다.",
            "example": "임플란트 치과 -> 치과 후보 확보 후 임플란트 가능 여부 검증",
        },
    },
    {
        "key": "historical_stale_entity",
        "group": "historical_failure",
        "title": "과거실패 · 이전 특정업체가 새 검색을 가둠",
        "request": "아까 치과 얘기한 뒤 중동 치과 몇 군데 찾아줘",
        "goal": "현재 요청이 업종 전체 탐색이면 과거 특정업체를 버리고 새 범위를 우선한다.",
        "difficulty": "보통",
        "expected_behaviors": [
            "현재 요청을 과거 문맥보다 우선한다.",
            "지시대명사가 없는 새 범위 검색에서는 이전 target_business를 제거한다.",
            "업종 전체 후보를 새로 조사한다.",
        ],
        "rule": {
            "trigger": "이전 대화에 특정 업체가 있지만 현재 요청은 새 지역/업종 전체 후보를 요구한다.",
            "instruction": "현재 요청의 범위를 우선하고 이전 특정업체를 자동 승계하지 않는다. 명백한 후속표현일 때만 기존 대상을 유지한다.",
            "example": "이전 A치과 -> '중동 치과 몇 군데'는 A치과 고정 해제",
        },
    },
    {
        "key": "historical_live_claim_without_work",
        "group": "historical_failure",
        "title": "과거실패 · 실제 작업 없이 조회한다고 말함",
        "request": "창원시청 주변 타이어 교체할 곳 알아봐",
        "goal": "음성 AI가 실제 조사 위임 전에는 조회·재시도를 했다고 말하지 않는다.",
        "difficulty": "어려움",
        "expected_behaviors": [
            "외부 조사가 필요하면 실제 백엔드 위임을 먼저 발생시킨다.",
            "작업이 시작되지 않았으면 '찾아보는 중'이라고 말하지 않는다.",
            "재시도한다고 말할 경우 실제 재시도 로직이 뒤따라야 한다.",
        ],
        "rule": {
            "trigger": "음성 대화에서 외부 검색·조회·전화가 필요한 요청을 받는다.",
            "instruction": "실제 조사 작업을 먼저 시작하거나 위임한 뒤에만 진행 중이라고 말한다. 실행되지 않은 재시도나 조회를 말로만 약속하지 않는다.",
            "example": "조회가 잘 안 돼 다시 해볼게요 -> 실제 재호출이 없으면 금지",
        },
    },
    {
        "key": "historical_candidates_not_answer",
        "group": "historical_failure",
        "title": "과거실패 · 후보목록을 최종답으로 착각",
        "request": "오늘 타이어 교체할 만한 곳 중 제일 괜찮은 데 골라줘",
        "goal": "업체를 몇 곳 찾는 것으로 끝내지 않고 사용자의 결정에 필요한 사실이 채워졌는지 평가한다.",
        "difficulty": "어려움",
        "expected_behaviors": [
            "최종 답에 필요한 가격·시간·거리·가능여부를 분리해 확인한다.",
            "핵심 사실이 빠졌으면 답이 완성되지 않았다고 판단한다.",
            "부족한 사실에 맞는 다음 조사수단을 선택한다.",
        ],
        "rule": {
            "trigger": "후보 업체나 자료는 찾았지만 사용자의 최종 선택에 필요한 핵심 사실이 일부 비어 있다.",
            "instruction": "후보 수가 아니라 expected_answer의 필수 사실 충족도를 기준으로 조사 완료 여부를 판단하고, 빈칸이 있으면 추가 조사한다.",
            "example": "타이어점 5곳 발견 + 가격/오늘 가능 여부 미확인 -> 조사 계속",
        },
    },
    {
        "key": "future_open_ended_family",
        "group": "future_complex",
        "title": "미래복잡 · 열린 질문에서 답의 형태 먼저 설계",
        "request": "오늘 애들이랑 뭐 하지?",
        "goal": "업체검색부터 하지 말고 활동 추천이라는 최종 답의 형태를 먼저 설계한다.",
        "difficulty": "어려움",
        "expected_behaviors": [
            "사용자의 목적을 가족 활동 결정으로 해석한다.",
            "날씨·시간·이동·연령·비용 등 필요한 판단요소를 역산한다.",
            "장소검색은 필요한 경우에만 하위 도구로 사용한다.",
        ],
        "rule": {
            "trigger": "사용자 요청이 업종이나 장소를 직접 말하지 않고 원하는 결과만 말한다.",
            "instruction": "먼저 사용자가 받아야 할 최종 답의 구조와 판단 기준을 설계하고, 그 빈칸을 채우는 데 필요한 조사도구만 선택한다.",
            "example": "오늘 애들이랑 뭐 하지? -> 활동추천 구조 설계 후 필요한 사실 조사",
        },
    },
    {
        "key": "future_symptom_triage",
        "group": "future_complex",
        "title": "미래복잡 · 증상 질문을 곧바로 업체검색으로 오인",
        "request": "차가 요철 지나갈 때 앞에서 덜컹거리는데 계속 타도 돼?",
        "goal": "정비소 검색보다 원인 범주·위험도·운행 지속 가능성·필요 점검을 먼저 판단한다.",
        "difficulty": "어려움",
        "expected_behaviors": [
            "질문의 1차 답을 위험도와 다음 행동으로 설계한다.",
            "진단 확정이 아닌 가능한 원인과 경고신호를 구분한다.",
            "정비소 검색은 점검이 필요하다고 판단될 때 후속 단계로 둔다.",
        ],
        "rule": {
            "trigger": "사용자가 증상·고장·이상현상을 설명하며 무엇을 해야 하는지 묻는다.",
            "instruction": "업체 탐색보다 먼저 위험도, 즉시 중단 필요 여부, 가능한 원인 범주, 필요한 점검을 구조화하고 확정 진단은 피한다.",
            "example": "덜컹 소리 -> 위험도/점검 우선, 정비소 검색은 후속",
        },
    },
    {
        "key": "future_document_review",
        "group": "future_complex",
        "title": "미래복잡 · 문서검토를 장소검색으로 오인",
        "request": "이 계약서 괜찮은지 봐줘",
        "goal": "문서 내용을 읽고 위험조항·불리한 조건·추가확인 사항을 답의 중심으로 삼는다.",
        "difficulty": "어려움",
        "expected_behaviors": [
            "첨부 문서나 이미지를 먼저 읽는다.",
            "위험조항과 사용자 의사결정에 필요한 내용을 구조화한다.",
            "장소검색을 기본값으로 사용하지 않는다.",
        ],
        "rule": {
            "trigger": "사용자가 계약서·문서·사진의 내용을 검토해 달라고 한다.",
            "instruction": "문서/이미지 분석을 우선하고 사용자가 결정해야 할 위험·의무·확인사항 중심으로 답을 구성한다. 장소검색을 자동 선택하지 않는다.",
            "example": "계약서 봐줘 -> 문서분석 + 위험조항 정리",
        },
    },
    {
        "key": "future_reservation_no_time",
        "group": "future_complex",
        "title": "미래복잡 · 희망시간 없는 예약 대행",
        "request": "내일 저녁에 부모님 모시고 갈 조용한 식당 알아서 예약해줘",
        "goal": "정확한 시각이 없다고 멈추지 않고 후보 업체가 제시하는 가능시간을 수집해 비교한다.",
        "difficulty": "매우어려움",
        "expected_behaviors": [
            "사용자에게 불필요하게 정확한 시각을 다시 묻지 않는다.",
            "후보를 찾은 뒤 업체별 가능한 시간대를 수집한다.",
            "조용함·이동·가격·가능시간을 비교해 선택 또는 사용자 확인으로 연결한다.",
        ],
        "rule": {
            "trigger": "예약 의도는 분명하지만 사용자가 정확한 희망시간을 지정하지 않았다.",
            "instruction": "시간 미정만으로 조사를 멈추지 말고 업체가 제시하는 가능한 시간대를 먼저 수집한 뒤 비교해 제안한다.",
            "example": "내일 저녁 예약 -> 업체별 17~22시 가능시간 수집 후 선택",
        },
    },
    {
        "key": "future_multi_party_coordination",
        "group": "future_complex",
        "title": "미래복잡 · 여러 상대방 일정 연쇄조정",
        "request": "이번 금요일 이사인데 인터넷 이전 설치, 도시가스 전입, 엘리베이터 사용시간까지 서로 안 겹치게 알아서 맞춰줘",
        "goal": "서로 다른 세 기관의 가능시간과 선후관계를 수집해 충돌 없는 실행계획을 만든다.",
        "difficulty": "매우어려움",
        "expected_behaviors": [
            "세 업무를 독립 검색으로 끝내지 않고 하나의 목표로 묶는다.",
            "각 기관의 가능시간·소요시간·변경조건을 수집한다.",
            "일정 충돌을 평가해 재협의하거나 대안을 찾는다.",
            "모든 의존조건이 맞아야 완료로 판단한다.",
        ],
        "rule": {
            "trigger": "하나의 사용자 목표를 위해 여러 업체·기관·사람의 일정이나 조건을 연쇄적으로 맞춰야 한다.",
            "instruction": "각 상대의 가능조건을 수집한 뒤 전체 제약조건을 함께 평가하고, 충돌이 있으면 재협의해 하나의 실행 가능한 계획으로 통합한다.",
            "example": "이사일 인터넷/가스/엘리베이터 -> 개별 조회가 아닌 통합 일정 조율",
        },
    },    {
        "key": "observed_research_timeout",
        "group": "observed_failure",
        "title": "관찰실패 · 상세검증 과다로 조회 타임아웃",
        "request": "창원시청 주변에 타이어 교체할 만한 곳 알아봐",
        "goal": "모든 상세검증이 끝날 때까지 첫 결과를 막지 않고 제한된 시간 안에 후보를 먼저 반환한다.",
        "difficulty": "어려움",
        "expected_behaviors": [
            "1차 후보 탐색과 상세검증을 같은 긴 임계경로에 모두 묶지 않는다.",
            "상위 후보만 우선 상세검증하고 나머지는 후보 자체를 먼저 반환한다.",
            "외부 제공자 응답시간과 검색 시도 횟수에 명확한 상한을 둔다.",
        ],
        "rule": {
            "trigger": "외부 장소검색·상세페이지·교차검증을 한 요청에서 연속 수행해 첫 응답이 늦어질 수 있다.",
            "instruction": "첫 결과는 빠르게 반환하고 상위 후보만 우선 상세검증한다. 외부 호출 수와 대기시간에 상한을 두고, 전체 상세검증 때문에 사용자가 첫 결과를 못 받는 구조를 피한다.",
            "example": "후보 8곳 -> 상위 4곳 우선 검증 + 나머지 후보 즉시 반환",
        },
    },

]


def _ensure_core_scenario(item):
    title = str(item["title"]).strip()
    scenario = TrainingScenario.objects.filter(
        category="범용",
        title=title,
    ).first()

    defaults = {
        "context": {
            "request": item["request"],
            "origin": item["group"],
            "curriculum_key": item["key"],
        },
        "goal": item["goal"],
        "difficulty": item["difficulty"],
        "expected_behaviors": item["expected_behaviors"],
        "provider_profile": {
            "curriculum": "goal-first-v1",
            "group": item["group"],
        },
    }

    if scenario is None:
        scenario = TrainingScenario.objects.create(
            category="범용",
            title=title,
            status="ready",
            **defaults,
        )
    else:
        changed_fields = []
        for field, value in defaults.items():
            if getattr(scenario, field) != value:
                setattr(scenario, field, value)
                changed_fields.append(field)
        if changed_fields:
            scenario.save(
                update_fields=changed_fields
            )

    return scenario


def ensure_core_curriculum():
    pairs = []

    for item in CORE_CURRICULUM:
        scenario = _ensure_core_scenario(item)
        rule_spec = item["rule"]
        rule = save_training_rule(
            category="",
            trigger=rule_spec["trigger"],
            instruction=rule_spec["instruction"],
            example=rule_spec["example"],
            source="core_curriculum",
            confidence=1.0,
        )
        pairs.append(
            {
                "scenario": scenario,
                "rule": rule,
                "key": item["key"],
                "group": item["group"],
            }
        )

    return pairs


def _diagnose_core_case(item):
    key = item["key"]
    detail = {}

    if key == "historical_reference_point":
        from .intent_brain_service import enhance_mission

        result = enhance_mission(
            {
                "summary": "창원시청 주변 타이어 교체 후보를 찾는다.",
                "intent": "조사",
                "response_mode": "research",
                "location": "창원시청",
                "location_context": {
                    "value": "창원시청",
                    "type": "reference_point",
                    "radius_hint_km": 3,
                },
                "required_facts": ["후보 업체", "거리"],
                "research_plan": [
                    {
                        "step": 1,
                        "goal": "기준장소 주변 후보 탐색",
                        "tool": "place_search",
                        "when": "항상",
                    },
                    {
                        "step": 2,
                        "goal": "거리 비교",
                        "tool": "map",
                        "when": "후보 확보 후",
                    },
                ],
                "may_need_phone_call": False,
            },
            item["request"],
        )
        passed = (
            result["location_context"]["type"]
            == "reference_point"
            and result["orchestration"][
                "requires_place_search"
            ]
        )
        detail = {
            "location_context": result["location_context"],
            "route": result["orchestration"]["route"],
        }

    elif key == "historical_narrow_subcategory":
        from .research_service import _matches_mission

        mission = {
            "category": "의료",
            "subject": "임플란트 가능한 치과",
            "search_terms": ["치과"],
            "subcategories": ["임플란트"],
        }
        passed = _matches_mission(
            {
                "place_name": "스마트치과",
                "category_name": "의료,건강 > 병원 > 치과",
            },
            mission,
        )
        detail = {
            "base_category_candidate_kept": passed,
        }

    elif key == "historical_stale_entity":
        from .mission_service import _normalize_search_scope

        result = _normalize_search_scope(
            {
                "search_mode": "follow_up_detail",
                "target_business": "처음말한치과",
                "ready_to_research": True,
            },
            (
                "[대화 문맥 - 참고용]\n"
                '{"target_business":"처음말한치과"}\n'
                "[현재 요청]\n"
                "창원시 의창구 중동에 치과 몇 군데 찾아줘"
            ),
        )
        passed = (
            result.get("target_business") is None
            and result.get("search_mode")
            == "category_discovery"
        )
        detail = {
            "target_business": result.get(
                "target_business"
            ),
            "search_mode": result.get(
                "search_mode"
            ),
        }

    elif key == "historical_live_claim_without_work":
        from .live_service import LIVE_SYSTEM_PROMPT

        passed = (
            "위임 없이" in LIVE_SYSTEM_PROMPT
            and "실제 백엔드 작업" in LIVE_SYSTEM_PROMPT
            and "재시도" in LIVE_SYSTEM_PROMPT
        )
        detail = {
            "delegation_guard_present": passed,
        }

    elif key == "historical_candidates_not_answer":
        from .research_evaluation_service import (
            evaluate_research_result,
        )

        result = evaluate_research_result(
            {
                "required_facts": [
                    "후보 업체",
                    "거리",
                    "가격",
                    "현재 작업 가능 여부",
                ],
                "may_need_phone_call": True,
                "orchestration": {
                    "tools": [
                        "place_search",
                        "phone",
                    ],
                },
            },
            [
                {
                    "name": "테스트타이어",
                    "address": "창원시 성산구",
                    "latitude": "35.22",
                    "longitude": "128.68",
                    "phone": "055-111-2222",
                }
            ],
            reference_origin={
                "latitude": "35.21",
                "longitude": "128.67",
            },
        )
        passed = (
            result["answer_ready"] is False
            and "가격" in result["missing_facts"]
            and "현재 작업 가능 여부"
            in result["missing_facts"]
            and "phone" in result["next_tools"]
        )
        detail = result

    elif key == "future_open_ended_family":
        from .intent_brain_service import enhance_mission

        result = enhance_mission(
            {
                "summary": "오늘 가족이 할 활동을 추천한다.",
                "intent": "비교",
                "response_mode": "research",
                "subject": "가족 활동",
                "comparison": "적합도",
                "required_facts": [
                    "오늘 가능한 활동",
                    "시간 적합성",
                    "이동 부담",
                ],
                "expected_answer": {
                    "type": "recommendation",
                    "summary": "가족 상황에 맞는 활동 후보와 추천 이유",
                    "must_include": [
                        "활동 후보",
                        "추천 이유",
                    ],
                },
                "research_plan": [
                    {
                        "step": 1,
                        "goal": "오늘 가능한 활동 조건 확인",
                        "tool": "web_search",
                        "when": "최신 정보가 필요할 때",
                    }
                ],
                "may_need_phone_call": False,
            },
            item["request"],
        )
        passed = (
            result["expected_answer"]["type"]
            == "recommendation"
            and result["orchestration"]["route"]
            == "web_research"
            and result["orchestration"][
                "requires_place_search"
            ]
            is False
        )
        detail = {
            "answer_type": result["expected_answer"]["type"],
            "route": result["orchestration"]["route"],
        }

    elif key == "future_symptom_triage":
        from .intent_brain_service import enhance_mission

        result = enhance_mission(
            {
                "summary": "차량 이상소리의 위험도와 필요한 점검을 판단한다.",
                "intent": "조사",
                "response_mode": "research",
                "subject": "차량 앞쪽 덜컹 소리",
                "required_facts": [
                    "위험 신호",
                    "가능한 원인 범주",
                    "운행 중단 필요 여부",
                    "점검 항목",
                ],
                "expected_answer": {
                    "type": "diagnosis_support",
                    "summary": "확정 진단이 아닌 위험도와 다음 행동",
                    "must_include": [
                        "위험도",
                        "경고신호",
                        "다음 행동",
                    ],
                },
                "research_plan": [
                    {
                        "step": 1,
                        "goal": "증상 기반 위험도 구조화",
                        "tool": "direct_reasoning",
                        "when": "항상",
                    },
                    {
                        "step": 2,
                        "goal": "필요한 경우 기술정보 확인",
                        "tool": "web_search",
                        "when": "추가 근거가 필요할 때",
                    },
                ],
                "may_need_phone_call": False,
            },
            item["request"],
        )
        passed = (
            result["expected_answer"]["type"]
            == "diagnosis_support"
            and result["orchestration"][
                "requires_place_search"
            ]
            is False
        )
        detail = {
            "answer_type": result["expected_answer"]["type"],
            "tools": result["orchestration"]["tools"],
        }

    elif key == "future_document_review":
        from .intent_brain_service import enhance_mission

        result = enhance_mission(
            {
                "summary": "계약서의 위험조항을 검토한다.",
                "intent": "조사",
                "response_mode": "research",
                "subject": "계약서",
                "required_facts": [
                    "불리한 조항",
                    "의무",
                    "추가확인 사항",
                ],
                "expected_answer": {
                    "type": "decision_support",
                    "summary": "계약 여부를 판단할 위험과 확인사항",
                    "must_include": [
                        "위험조항",
                        "추가확인 사항",
                    ],
                },
                "research_plan": [
                    {
                        "step": 1,
                        "goal": "문서 내용 읽기",
                        "tool": "image",
                        "when": "첨부 문서가 있을 때",
                    },
                    {
                        "step": 2,
                        "goal": "위험조항 분석",
                        "tool": "direct_reasoning",
                        "when": "문서 추출 후",
                    },
                ],
                "may_need_phone_call": False,
            },
            item["request"],
        )
        passed = (
            result["orchestration"]["route"]
            == "image_research"
            and result["orchestration"][
                "requires_place_search"
            ]
            is False
        )
        detail = result["orchestration"]

    elif key == "future_reservation_no_time":
        from .intent_brain_service import enhance_mission

        result = enhance_mission(
            {
                "summary": "내일 저녁 조용한 식당을 찾아 예약까지 연결한다.",
                "intent": "예약",
                "response_mode": "research",
                "subject": "부모님과 저녁 식사",
                "constraints": ["내일 저녁", "조용한 곳"],
                "required_facts": [
                    "후보 업체",
                    "가능한 예약시간대",
                    "가격대",
                ],
                "clarification_questions": [],
                "ready_to_research": True,
                "expected_answer": {
                    "type": "execution_result",
                    "summary": "예약 가능한 후보와 시간대를 비교한 결과",
                    "must_include": [
                        "가능시간",
                        "추천 이유",
                    ],
                },
                "research_plan": [
                    {
                        "step": 1,
                        "goal": "식당 후보 수집",
                        "tool": "place_search",
                        "when": "항상",
                    },
                    {
                        "step": 2,
                        "goal": "가능한 예약시간 확인",
                        "tool": "phone",
                        "when": "온라인으로 확정되지 않을 때",
                    },
                ],
                "may_need_phone_call": True,
            },
            item["request"],
        )
        passed = (
            result["expected_answer"]["type"]
            == "execution_result"
            and "phone" in result["orchestration"]["tools"]
            and result.get("clarification_questions", [])
            == []
        )
        detail = {
            "tools": result["orchestration"]["tools"],
            "clarifications": result.get(
                "clarification_questions",
                [],
            ),
        }

    elif key == "future_multi_party_coordination":
        from .intent_brain_service import enhance_mission

        result = enhance_mission(
            {
                "summary": "이사 관련 세 업무의 일정을 충돌 없이 조율한다.",
                "intent": "처리",
                "response_mode": "research",
                "subject": "이사 당일 다기관 일정 조율",
                "required_facts": [
                    "인터넷 설치 가능시간",
                    "도시가스 전입 가능시간",
                    "엘리베이터 사용 가능시간",
                    "각 업무 소요시간",
                ],
                "expected_answer": {
                    "type": "plan",
                    "summary": "충돌 없이 실행 가능한 통합 일정",
                    "must_include": [
                        "업무별 시간",
                        "선후관계",
                        "충돌 여부",
                    ],
                },
                "research_plan": [
                    {
                        "step": 1,
                        "goal": "각 기관 가능시간 수집",
                        "tool": "phone",
                        "when": "현재 가능시간 확인",
                    },
                    {
                        "step": 2,
                        "goal": "시간 충돌 평가",
                        "tool": "direct_reasoning",
                        "when": "모든 시간 수집 후",
                    },
                    {
                        "step": 3,
                        "goal": "충돌 시 재협의",
                        "tool": "phone",
                        "when": "일정 충돌이 있을 때",
                    },
                ],
                "completion_criteria": [
                    "세 업무 모두 가능한 시간이 확인된다.",
                    "업무 사이 시간 충돌이 없다.",
                ],
                "may_need_phone_call": True,
            },
            item["request"],
        )
        passed = (
            result["expected_answer"]["type"]
            == "plan"
            and result["orchestration"][
                "may_require_phone"
            ]
            and len(
                result["completion_criteria"]
            )
            >= 2
        )
        detail = {
            "answer_type": result["expected_answer"]["type"],
            "tools": result["orchestration"]["tools"],
            "completion_criteria": result[
                "completion_criteria"
            ],
        }

    elif key == "observed_research_timeout":
        from .research_service import (
            FAST_DETAIL_ENRICH_LIMIT,
            MAX_KAKAO_QUERY_ATTEMPTS,
        )

        passed = (
            FAST_DETAIL_ENRICH_LIMIT <= 4
            and MAX_KAKAO_QUERY_ATTEMPTS <= 5
        )
        detail = {
            "detail_enrichment_limit": FAST_DETAIL_ENRICH_LIMIT,
            "max_kakao_query_attempts": MAX_KAKAO_QUERY_ATTEMPTS,
        }

    else:
        passed = False
        detail = {
            "error": "진단 구현이 없는 커리큘럼 항목",
        }

    return passed, detail


def run_core_curriculum_diagnostics():
    pairs = ensure_core_curriculum()
    pair_by_key = {
        item["key"]: item
        for item in pairs
    }
    runs = []

    for item in CORE_CURRICULUM:
        passed, detail = _diagnose_core_case(
            item
        )
        pair = pair_by_key[item["key"]]
        scenario = pair["scenario"]
        rule = pair["rule"]

        mistakes = (
            []
            if passed
            else [
                (
                    "현재 구현이 이 훈련 시나리오의 "
                    "기대행동을 아직 충족하지 못함"
                )
            ]
        )

        run = TrainingRun.objects.create(
            scenario=scenario,
            mode="curriculum_regression",
            transcript=[
                {
                    "role": "user",
                    "content": item["request"],
                },
                {
                    "role": "evaluator",
                    "content": detail,
                },
            ],
            score=100 if passed else 0,
            mistakes=mistakes,
            learned_rules=[rule.id],
        )
        scenario.status = (
            "trained"
            if passed
            else "ready"
        )
        scenario.save(
            update_fields=["status"]
        )
        runs.append(run)

    return runs


def _signature(category, trigger, instruction):
    raw = "|".join([str(category or "").strip().lower(), str(trigger or "").strip().lower(), str(instruction or "").strip().lower()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_training_rule(*, category="", trigger, instruction, example="", source="admin", confidence=1.0):
    trigger = str(trigger or "").strip()
    instruction = str(instruction or "").strip()
    category = str(category or "").strip()
    if not trigger or not instruction:
        raise ValueError("훈련 규칙의 상황과 지침이 필요합니다.")

    rule, _ = TrainingRule.objects.update_or_create(
        signature=_signature(category, trigger, instruction),
        defaults={
            "category": category,
            "trigger": trigger,
            "instruction": instruction,
            "example": str(example or "").strip(),
            "source": str(source or "admin").strip(),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "active": True,
        },
    )
    return rule


def active_rules_text(category=None, limit=30):
    # Mission 생성은 읽기 경로다. 여기서 DB upsert를 수행하면
    # Cloud Run + SQLite 환경에서 지연/잠금이 생겨 실제 사용자
    # 요청이 실패할 수 있다. 핵심 커리큘럼 규칙은 코드에서
    # 읽기 전용으로 주입하고, 관리자/자동훈련 규칙만 DB에서 읽는다.
    safe_limit = max(1, min(100, int(limit)))
    category = str(category or "").strip()

    lines = []
    seen = set()

    for item in CORE_CURRICULUM:
        rule = item.get("rule")
        if not isinstance(rule, dict):
            continue

        trigger = str(
            rule.get("trigger") or ""
        ).strip()
        instruction = str(
            rule.get("instruction") or ""
        ).strip()
        if not trigger or not instruction:
            continue

        signature = _signature(
            "",
            trigger,
            instruction,
        )
        if signature in seen:
            continue

        seen.add(signature)
        lines.append(
            f"- 상황: {trigger} / 지침: {instruction}"
        )
        if len(lines) >= safe_limit:
            return "\n".join(lines)

    query = TrainingRule.objects.filter(
        active=True
    ).exclude(source="core_curriculum")

    if category:
        query = query.filter(
            category__in=["", category]
        )

    for rule in query[:safe_limit]:
        signature = _signature(
            rule.category,
            rule.trigger,
            rule.instruction,
        )
        if signature in seen:
            continue

        seen.add(signature)
        lines.append(
            f"- 상황: {rule.trigger} / 지침: {rule.instruction}"
        )
        if len(lines) >= safe_limit:
            break

    return "\n".join(lines)


def _actual_categories():
    values = ResearchRecord.objects.exclude(category="").values_list("category", flat=True).distinct()[:30]
    result = [str(item).strip() for item in values if str(item).strip()]
    return result or ["범용"]


def generate_training_scenarios(category=None, limit=10):
    limit = max(1, min(30, int(limit)))
    requested = str(category or "").strip()
    categories = [requested] if requested else _actual_categories()
    created = []

    for target_category in categories:
        for title, expected in AUTO_SCENARIO_AXES:
            if len(created) >= limit:
                return created
            scenario, was_created = TrainingScenario.objects.get_or_create(
                category=target_category,
                title=f"{target_category} · {title}",
                defaults={
                    "context": {"issue": title},
                    "goal": "사용자의 실제 목표를 유지하면서 필요한 정보만 확인해 최적 선택 또는 예약까지 연결한다.",
                    "difficulty": "보통",
                    "expected_behaviors": [expected],
                    "provider_profile": {"variation": title},
                    "status": "ready",
                },
            )
            if was_created:
                created.append(scenario)

    return created


def run_auto_training(*, api_key=None, limit=4, category=None):
    key = get_api_key(api_key)
    if not key:
        raise ValueError("OpenAI API Key가 필요합니다.")

    limit = max(1, min(6, int(limit)))
    category = str(category or "").strip()
    query = TrainingScenario.objects.filter(status="ready")
    if category:
        query = query.filter(category=category)

    scenarios = list(query[:limit])
    if not scenarios:
        generate_training_scenarios(category=category or None, limit=limit)
        query = TrainingScenario.objects.filter(status="ready")
        if category:
            query = query.filter(category=category)
        scenarios = list(query[:limit])

    client = OpenAI(api_key=key, timeout=50.0, max_retries=0)
    runs = []

    for scenario in scenarios:
        learned = active_rules_text(category=scenario.category)
        prompt = (
            "ARABA 통화 에이전트의 훈련 상황을 시뮬레이션하고 평가하라. "
            f"카테고리={scenario.category}; 상황={scenario.context}; 목표={scenario.goal}; "
            f"기대행동={scenario.expected_behaviors}; 기존규칙={learned or '없음'}. "
            "업체 담당자는 일부러 모호하거나 불리한 답도 할 수 있다. "
            "ARABA가 사용자 목표를 놓치지 않고 질문하도록 4~8턴 대화를 만들고, "
            "실수가 있으면 재발방지 규칙을 만든다. "
            "JSON 객체로 transcript(list), score(0~100), mistakes(list), learned_rules(list of trigger/instruction/example)를 반환한다."
        )
        response = client.responses.create(model="gpt-5-mini", input=prompt, max_output_tokens=2200)
        raw = response.output_text.strip()
        if raw.startswith("```"):
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"transcript": [], "score": 0, "mistakes": ["평가 JSON 파싱 실패"], "learned_rules": []}

        try:
            score = max(0, min(100, int(data.get("score", 0))))
        except (TypeError, ValueError):
            score = 0

        rule_ids = []
        learned_rules = data.get("learned_rules") if isinstance(data.get("learned_rules"), list) else []
        for item in learned_rules:
            if not isinstance(item, dict):
                continue
            trigger = str(item.get("trigger") or "").strip()
            instruction = str(item.get("instruction") or "").strip()
            if not trigger or not instruction:
                continue
            rule = save_training_rule(
                category=scenario.category,
                trigger=trigger,
                instruction=instruction,
                example=str(item.get("example") or "").strip(),
                source="auto",
                confidence=0.8,
            )
            rule_ids.append(rule.id)

        run = TrainingRun.objects.create(
            scenario=scenario,
            mode="auto",
            transcript=data.get("transcript") if isinstance(data.get("transcript"), list) else [],
            score=score,
            mistakes=data.get("mistakes") if isinstance(data.get("mistakes"), list) else [],
            learned_rules=rule_ids,
        )
        scenario.status = "trained"
        scenario.save(update_fields=["status"])
        runs.append(run)

    return runs


def training_status():
    return {
        "scenario_count": TrainingScenario.objects.count(),
        "ready_scenario_count": TrainingScenario.objects.filter(status="ready").count(),
        "rule_count": TrainingRule.objects.filter(active=True).count(),
        "run_count": TrainingRun.objects.count(),
        "recent_runs": [
            {
                "id": run.id,
                "mode": run.mode,
                "score": run.score,
                "scenario": run.scenario.title if run.scenario else None,
                "created_at": run.created_at.isoformat(),
            }
            for run in TrainingRun.objects.select_related("scenario")[:20]
        ],
    }
