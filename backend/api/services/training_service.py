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
    query = TrainingRule.objects.filter(active=True)
    category = str(category or "").strip()
    if category:
        query = query.filter(category__in=["", category])
    rules = list(query[: max(1, min(100, int(limit)))])
    return "\n".join(
        f"- 상황: {rule.trigger} / 지침: {rule.instruction}"
        for rule in rules
    )


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
