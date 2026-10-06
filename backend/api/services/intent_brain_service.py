import re


VALID_ANSWER_TYPES = {
    "direct_answer",
    "fact_summary",
    "comparison",
    "recommendation",
    "diagnosis_support",
    "decision_support",
    "execution_result",
    "plan",
}

VALID_LOCATION_TYPES = {
    "administrative_area",
    "reference_point",
    "none",
}

VALID_TOOL_NAMES = {
    "direct_reasoning",
    "place_search",
    "map",
    "web_search",
    "records",
    "image",
    "phone",
}


def _clean_text(value):
    return " ".join(
        str(value or "").split()
    ).strip()


def _clean_list(value):
    if not isinstance(value, list):
        return []

    result = []
    for item in value:
        text = _clean_text(item)
        if text and text not in result:
            result.append(text)
    return result


def _fallback_answer_type(mission):
    intent = _clean_text(
        mission.get("intent")
    )
    comparison = _clean_text(
        mission.get("comparison")
    )
    response_mode = _clean_text(
        mission.get("response_mode")
    )

    if response_mode == "answer":
        return "direct_answer"
    if intent in {"예약", "구매", "처리"}:
        return "execution_result"
    if comparison and comparison not in {
        "없음",
        "none",
    }:
        return "comparison"
    if intent in {"비교"}:
        return "comparison"
    if intent in {"조사", "문의"}:
        return "recommendation"

    return "decision_support"


def _fallback_goal(mission):
    summary = _clean_text(
        mission.get("summary")
    )
    subject = _clean_text(
        mission.get("subject")
    )
    intent = _clean_text(
        mission.get("intent")
    )

    if summary:
        return summary
    if subject and intent:
        return f"{subject}에 대해 {intent} 목적을 달성한다."
    if subject:
        return f"{subject}에 대해 사용자가 필요한 결론을 얻는다."
    return "사용자의 현재 요청을 정확히 해결한다."


def _fallback_expected_answer(
    mission,
):
    required_facts = _clean_list(
        mission.get("required_facts")
    )
    answer_type = _fallback_answer_type(
        mission
    )

    return {
        "type": answer_type,
        "summary": (
            "사용자가 다음 행동이나 결정을 할 수 있도록 "
            "결론과 근거를 함께 제시한다."
        ),
        "must_include": required_facts,
    }


def _normalize_expected_answer(
    mission,
):
    value = mission.get(
        "expected_answer"
    )

    if not isinstance(value, dict):
        return _fallback_expected_answer(
            mission
        )

    answer_type = _clean_text(
        value.get("type")
    )
    if answer_type not in VALID_ANSWER_TYPES:
        answer_type = _fallback_answer_type(
            mission
        )

    summary = _clean_text(
        value.get("summary")
    )
    if not summary:
        summary = (
            "사용자가 다음 행동이나 결정을 할 수 있도록 "
            "결론과 근거를 함께 제시한다."
        )

    must_include = _clean_list(
        value.get("must_include")
    )
    if not must_include:
        must_include = _clean_list(
            mission.get("required_facts")
        )

    return {
        "type": answer_type,
        "summary": summary,
        "must_include": must_include,
    }


def _normalize_location_context(
    mission,
):
    value = mission.get(
        "location_context"
    )
    location = _clean_text(
        mission.get("location")
    )

    if not isinstance(value, dict):
        return {
            "value": location or None,
            "type": (
                "administrative_area"
                if location
                else "none"
            ),
            "radius_hint_km": None,
        }

    location_type = _clean_text(
        value.get("type")
    )
    if location_type not in VALID_LOCATION_TYPES:
        location_type = (
            "administrative_area"
            if location
            else "none"
        )

    raw_radius = value.get(
        "radius_hint_km"
    )
    try:
        radius = (
            float(raw_radius)
            if raw_radius is not None
            else None
        )
    except (TypeError, ValueError):
        radius = None

    if radius is not None:
        radius = max(0.1, min(radius, 50.0))

    return {
        "value": (
            _clean_text(
                value.get("value")
            )
            or location
            or None
        ),
        "type": location_type,
        "radius_hint_km": radius,
    }


def _normalize_evidence_needed(
    mission,
):
    raw = mission.get(
        "evidence_needed"
    )
    result = []

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue

            fact = _clean_text(
                item.get("fact")
            )
            if not fact:
                continue

            sources = _clean_list(
                item.get("source_priority")
            )
            sources = [
                source
                for source in sources
                if source in VALID_TOOL_NAMES
            ]

            result.append(
                {
                    "fact": fact,
                    "source_priority": sources,
                    "required": (
                        item.get("required")
                        is not False
                    ),
                }
            )

    if result:
        return result

    return [
        {
            "fact": fact,
            "source_priority": [],
            "required": True,
        }
        for fact in _clean_list(
            mission.get("required_facts")
        )
    ]


def _normalize_research_plan(
    mission,
):
    raw = mission.get(
        "research_plan"
    )
    result = []

    if isinstance(raw, list):
        for index, item in enumerate(
            raw,
            start=1,
        ):
            if not isinstance(item, dict):
                continue

            goal = _clean_text(
                item.get("goal")
            )
            tool = _clean_text(
                item.get("tool")
            )
            if (
                not goal
                or tool not in VALID_TOOL_NAMES
            ):
                continue

            result.append(
                {
                    "step": index,
                    "goal": goal,
                    "tool": tool,
                    "when": _clean_text(
                        item.get("when")
                    )
                    or "항상",
                }
            )

    if result:
        return result

    response_mode = _clean_text(
        mission.get("response_mode")
    )
    may_call = (
        mission.get("may_need_phone_call")
        is True
    )

    if response_mode == "answer":
        return [
            {
                "step": 1,
                "goal": "현재 확인된 정보로 답을 완성한다.",
                "tool": "direct_reasoning",
                "when": "외부 최신정보가 필요하지 않을 때",
            }
        ]

    fallback = [
        {
            "step": 1,
            "goal": "답에 필요한 외부 사실과 후보를 수집한다.",
            "tool": "place_search",
            "when": "장소나 업체 탐색이 필요한 경우",
        },
        {
            "step": 2,
            "goal": "수집한 사실을 비교하고 빈칸을 찾는다.",
            "tool": "web_search",
            "when": "추가 검증이나 최신정보가 필요한 경우",
        },
    ]

    if may_call:
        fallback.append(
            {
                "step": 3,
                "goal": "검색으로 확인되지 않는 핵심 사실을 직접 확인한다.",
                "tool": "phone",
                "when": "가격, 재고, 가능시간 등 결정적 사실이 남아 있을 때",
            }
        )

    return fallback


def _normalize_completion_criteria(
    mission,
):
    value = _clean_list(
        mission.get(
            "completion_criteria"
        )
    )

    if value:
        return value

    must_include = (
        _normalize_expected_answer(
            mission
        )["must_include"]
    )

    if must_include:
        return [
            (
                "필수 사실을 확인하거나, 확인 불가 여부를 "
                "근거와 함께 명확히 표시한다."
            ),
            (
                "사용자가 다음 행동이나 결정을 할 수 있는 "
                "수준의 결론을 제시한다."
            ),
        ]

    return [
        "사용자의 핵심 질문에 직접 답한다.",
        "확실한 사실과 미확인 사실을 구분한다.",
    ]


def enhance_mission(
    mission,
    request_text="",
):
    if not isinstance(mission, dict):
        raise ValueError(
            "Mission은 객체 형식이어야 합니다."
        )

    mission = dict(mission)

    mission["user_goal"] = (
        _clean_text(
            mission.get("user_goal")
        )
        or _fallback_goal(mission)
    )

    mission["decision_needed"] = (
        _clean_text(
            mission.get("decision_needed")
        )
        or (
            "사용자가 요청한 목적을 달성하기 위해 "
            "가장 적절한 다음 행동을 결정한다."
        )
    )

    mission["expected_answer"] = (
        _normalize_expected_answer(
            mission
        )
    )

    mission["known_facts"] = (
        mission.get("known_facts")
        if isinstance(
            mission.get("known_facts"),
            dict,
        )
        else {}
    )

    mission["unknown_facts"] = (
        _clean_list(
            mission.get("unknown_facts")
        )
        or _clean_list(
            mission.get("required_facts")
        )
    )

    mission["evidence_needed"] = (
        _normalize_evidence_needed(
            mission
        )
    )

    mission["research_plan"] = (
        _normalize_research_plan(
            mission
        )
    )

    mission["completion_criteria"] = (
        _normalize_completion_criteria(
            mission
        )
    )

    target_confidence = _clean_text(
        mission.get("confidence_target")
    ).lower()
    if target_confidence not in {
        "high",
        "medium",
        "low",
    }:
        target_confidence = "high"

    mission["confidence_target"] = (
        target_confidence
    )

    mission["location_context"] = (
        _normalize_location_context(
            mission
        )
    )

    current_request = _clean_text(
        request_text
    )
    if current_request:
        mission["brain_version"] = "goal-first-v1"

    return mission
