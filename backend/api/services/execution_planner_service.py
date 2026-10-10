REALTIME_FIELDS = {
    "availability",
    "stock",
}

DETAIL_FIELDS = {
    "parking_available",
    "closing_time",
    "opening_time",
    "opening_day",
    "price",
    "rating",
    "service",
}


def _criteria(mission):
    value = mission.get("criteria")
    if not isinstance(value, list):
        return []
    return [
        dict(item)
        for item in value
        if isinstance(item, dict)
    ]


def _task(task_id, title, *, tool, reason, depends_on=None, blocking=True):
    return {
        "id": task_id,
        "title": title,
        "tool": tool,
        "reason": reason,
        "depends_on": list(depends_on or []),
        "blocking": blocking,
        "status": "pending",
    }


def build_execution_plan(mission):
    if not isinstance(mission, dict):
        return {
            "version": "execution-plan-v1",
            "tasks": [],
        }

    intent = str(
        mission.get("intent") or ""
    ).strip()
    search_mode = str(
        mission.get("search_mode") or ""
    ).strip()
    attributes = mission.get("attributes")
    attributes = (
        dict(attributes)
        if isinstance(attributes, dict)
        else {}
    )
    location_context = mission.get(
        "location_context"
    )
    location_context = (
        dict(location_context)
        if isinstance(location_context, dict)
        else {}
    )
    criteria = _criteria(mission)
    fields = {
        str(item.get("field") or "").strip()
        for item in criteria
    }

    tasks = []

    if intent in {"place_search", "place_detail"}:
        if (
            location_context.get("type")
            == "device_location"
        ):
            tasks.append(
                _task(
                    "resolve_device_location",
                    "현재 위치를 검색 기준점으로 확정",
                    tool="device_location",
                    reason="내 주변·여기·현재 위치 기반 요청",
                )
            )

        reuse_recent = (
            attributes.get(
                "reuse_recent_results"
            )
            is True
        )
        if reuse_recent:
            tasks.append(
                _task(
                    "load_recent_candidates",
                    "직전 후보 집합 고정",
                    tool="conversation_context",
                    reason="후속 조건은 신규 검색이 아니라 기존 후보 재판정",
                )
            )
        else:
            tasks.append(
                _task(
                    "search_business_graph",
                    "ARABA 상점 DB 우선 조회",
                    tool="business_graph",
                    reason="이미 검증한 상점 데이터를 재사용해 속도와 일관성 확보",
                )
            )
            tasks.append(
                _task(
                    "discover_missing_candidates",
                    "부족한 후보만 외부 장소검색으로 보충",
                    tool="kakao_local",
                    reason="DB 후보가 부족할 때만 신규 상점 발견",
                    depends_on=["search_business_graph"],
                )
            )

        tasks.append(
            _task(
                "verify_business_identity",
                "상호·주소로 동일 업체 검증",
                tool="identity_guardrail",
                reason="다른 업종·다른 업체의 사진과 정보를 섞지 않기 위해 필요",
                depends_on=(
                    ["load_recent_candidates"]
                    if reuse_recent
                    else [
                        "search_business_graph",
                        "discover_missing_candidates",
                    ]
                ),
            )
        )

        if fields & DETAIL_FIELDS or mission.get(
            "needs_fresh_data"
        ):
            tasks.append(
                _task(
                    "enrich_missing_facts",
                    "조건 판정에 필요한 부족 정보만 보강",
                    tool="naver_web_google_places",
                    reason="영업시간·가격·주차·사진 등 근거가 없는 필드만 조사",
                    depends_on=["verify_business_identity"],
                )
            )

        tasks.append(
            _task(
                "verify_place_photo",
                "업체 신원이 일치하는 사진만 연결",
                tool="google_places_photos",
                reason="상점 카드에 다른 건물·다른 업체 사진이 노출되는 오류 방지",
                depends_on=["verify_business_identity"],
                blocking=False,
            )
        )

        if (
            "availability" in fields
            or any(
                marker in str(
                    mission.get("user_goal")
                    or mission.get("summary")
                    or ""
                )
                for marker in (
                    "지금",
                    "현재",
                    "주문",
                    "영업",
                )
            )
        ):
            tasks.append(
                _task(
                    "evaluate_current_kst",
                    "현재 KST 기준 영업·주문 가능 상태 판정",
                    tool="temporal_engine",
                    reason="현재 시각이 확인된 영업시간 범위에 들어오는지 계산",
                    depends_on=["enrich_missing_facts"],
                )
            )

        if fields & REALTIME_FIELDS:
            tasks.append(
                _task(
                    "query_business_agent",
                    "사업자 AI에 실시간 상태 질의",
                    tool="business_agent_gateway",
                    reason="재고·예약 슬롯 등 저장 데이터로 확정할 수 없는 실시간 사실 확인",
                    depends_on=["verify_business_identity"],
                    blocking=False,
                )
            )

        if criteria:
            tasks.append(
                _task(
                    "compare_all_conditions",
                    "모든 필수 조건의 교집합 판정",
                    tool="matching_engine",
                    reason="조건 하나라도 미확인이면 충족으로 추정하지 않음",
                    depends_on=[
                        item["id"]
                        for item in tasks
                        if item["id"]
                        in {
                            "enrich_missing_facts",
                            "evaluate_current_kst",
                            "query_business_agent",
                        }
                    ],
                )
            )

    if (
        intent == "phone_action"
        or search_mode == "reservation"
        or any(
            marker in str(
                mission.get("user_goal")
                or mission.get("summary")
                or ""
            )
            for marker in (
                "예약",
                "주문해",
                "구매해",
            )
        )
    ):
        tasks.extend(
            [
                _task(
                    "prepare_transaction",
                    "실행 조건과 사용자 승인 범위 확인",
                    tool="transaction_guardrail",
                    reason="예약·주문 전 대상·시간·금액·취소조건 확인",
                ),
                _task(
                    "execute_transaction",
                    "사업자 AI 또는 허용된 대체 채널로 실행",
                    tool="business_agent_gateway",
                    reason="사용자 승인 범위 안에서 예약·주문 완료",
                    depends_on=["prepare_transaction"],
                ),
                _task(
                    "confirm_transaction",
                    "확정번호·조건·결과 검증 후 사용자에게 보고",
                    tool="transaction_verifier",
                    reason="실제 완료 여부를 말이 아니라 증거로 확인",
                    depends_on=["execute_transaction"],
                ),
            ]
        )

    return {
        "version": "execution-plan-v1",
        "task_count": len(tasks),
        "tasks": tasks,
        "completion_rule": (
            "blocking=true인 모든 과제가 완료되거나, "
            "근거 부족으로 명시적 unknown 상태가 되기 전에는 완료로 보고하지 않는다."
        ),
    }
