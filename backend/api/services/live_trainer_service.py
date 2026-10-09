import json

from openai import OpenAI

from ..models import TrainingRun, TrainingScenario
from .openai_service import get_api_key
from .training_service import save_training_rule


TRAINER_DIAGNOSIS_MODEL = "gpt-5-mini"


def _trim(value, limit):
    return str(value or "").strip()[:limit]


def _safe_context(value):
    if not isinstance(value, dict):
        return {}
    allowed = {
        "mission",
        "businesses",
        "request_context",
        "badge",
        "source",
    }
    return {
        key: value[key]
        for key in allowed
        if key in value
    }


def _parse_json(text):
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = (
            raw.removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _record_scenario(
    *,
    category,
    request_text,
    assistant_response,
    trainer_note,
    diagnosis,
    actor_role="trainer",
):
    title_tail = _trim(request_text, 110) or "훈련사 피드백"
    scenario = TrainingScenario.objects.create(
        category=_trim(category, 80),
        title=f"실시간 훈련 · {title_tail}",
        context={
            "request": request_text,
            "assistant_response": assistant_response,
            "trainer_note": trainer_note,
            "diagnosis": diagnosis,
        },
        goal=(
            "훈련사가 지적한 실패 원인을 재현하고 같은 유형의 "
            "사용자 요청에서 올바른 행동을 수행한다."
        ),
        difficulty="실전",
        expected_behaviors=[
            _trim(
                diagnosis.get("corrective_instruction")
                or trainer_note
                or "같은 오류를 반복하지 않는다.",
                1200,
            )
        ],
        provider_profile={
            "source": (
                "live_trainer"
                if actor_role == "trainer"
                else "live_user_feedback"
            ),
            "actor_role": actor_role,
            "root_cause_type": _trim(
                diagnosis.get("root_cause_type"),
                80,
            ),
        },
        status="trained",
    )
    return scenario


def record_correct_feedback(
    *,
    category="",
    request_text="",
    assistant_response="",
    context=None,
):
    scenario = TrainingScenario.objects.create(
        category=_trim(category, 80),
        title=f"실시간 정상 예시 · {_trim(request_text, 110) or '사용자 요청'}",
        context={
            "request": _trim(request_text, 5000),
            "assistant_response": _trim(assistant_response, 7000),
            "context": _safe_context(context),
        },
        goal="현재 행동을 정상 사례로 보존한다.",
        difficulty="실전",
        expected_behaviors=["현재 응답 흐름을 정상 사례로 유지한다."],
        provider_profile={"source": "live_trainer"},
        status="trained",
    )
    run = TrainingRun.objects.create(
        scenario=scenario,
        mode="live_trainer_positive",
        transcript=[
            {"role": "user", "content": _trim(request_text, 5000)},
            {"role": "assistant", "content": _trim(assistant_response, 7000)},
            {"role": "trainer", "content": "정상"},
        ],
        score=100,
        mistakes=[],
        learned_rules=[],
    )
    return {
        "status": "positive_example_saved",
        "run_id": run.id,
        "scenario_id": scenario.id,
        "learned": False,
        "message": "정상 사례로 저장했어요.",
    }


def analyze_and_learn_trainer_feedback(
    *,
    api_key=None,
    category="",
    request_text="",
    assistant_response="",
    trainer_note="",
    expected_behavior="",
    context=None,
    actor_role="trainer",
):
    request_text = _trim(request_text, 5000)
    assistant_response = _trim(assistant_response, 7000)
    trainer_note = _trim(trainer_note, 4000)
    expected_behavior = _trim(expected_behavior, 4000)
    category = _trim(category, 80)
    actor_role = (
        "trainer"
        if str(actor_role or "").strip().lower() == "trainer"
        else "user"
    )
    safe_context = _safe_context(context)

    if not request_text:
        raise ValueError("문제가 발생한 사용자 요청이 필요합니다.")
    if not assistant_response:
        raise ValueError("평가할 ARABA 응답이 필요합니다.")
    if not trainer_note and not expected_behavior:
        raise ValueError("무엇이 잘못됐는지 또는 원하는 동작을 입력해주세요.")

    key = get_api_key(api_key)
    if not key:
        raise ValueError("OpenAI API Key가 필요합니다.")

    prompt = f"""
너는 ARABA 실시간 훈련 진단기다.
훈련사가 실제 앱 테스트 중 잘못된 결과를 표시했다.
한 사례에 과적합하지 말고 재발 가능한 원인을 분류하고,
즉시 대화 정책 규칙으로 학습 가능한 문제인지 코드/데이터/외부 공급자 수정이 필요한 문제인지 구분하라.

[사용자 요청]
{request_text}

[ARABA 응답]
{assistant_response}

[훈련사 지적]
{trainer_note or "없음"}

[원하는 동작]
{expected_behavior or "별도 입력 없음"}

[실행 문맥]
{json.dumps(safe_context, ensure_ascii=False)[:10000]}

반드시 JSON 객체 하나만 반환:
{{
  "root_cause_type": "intent|context|location|search|data|matching|action|voice|ui|provider|code|other",
  "root_cause": "구체적인 원인",
  "trigger": "이 규칙이 적용되어야 하는 재발 상황",
  "corrective_instruction": "ARABA가 다음부터 지켜야 할 구체적 행동 규칙",
  "can_learn_as_rule": true,
  "needs_code_fix": false,
  "verification": "다음 테스트에서 확인할 기준"
}}

판단 원칙:
- 단순 프롬프트/대화 정책으로 재발 방지가 가능하면 can_learn_as_rule=true.
- 검색 API 미호출, 앱 상태 단절, 잘못된 데이터 병합, UI 이벤트 누락, 코드 흐름 오류면 needs_code_fix=true.
- 사실을 모르면 추정하지 않는다.
- 사용자 최초 목표와 후속 문맥 유지는 최우선이다.
""".strip()

    client = OpenAI(
        api_key=key,
        timeout=45.0,
        max_retries=0,
    )
    response = client.responses.create(
        model=TRAINER_DIAGNOSIS_MODEL,
        input=prompt,
        max_output_tokens=1200,
    )
    diagnosis = _parse_json(response.output_text)

    if not diagnosis:
        diagnosis = {
            "root_cause_type": "other",
            "root_cause": "자동 원인 분석 결과를 구조화하지 못했습니다.",
            "trigger": trainer_note or request_text,
            "corrective_instruction": expected_behavior or trainer_note,
            "can_learn_as_rule": False,
            "needs_code_fix": True,
            "verification": "동일 요청을 다시 실행해 수동 확인",
        }

    diagnosis["root_cause_type"] = _trim(
        diagnosis.get("root_cause_type") or "other",
        80,
    )
    diagnosis["root_cause"] = _trim(
        diagnosis.get("root_cause"),
        2000,
    )
    diagnosis["trigger"] = _trim(
        diagnosis.get("trigger") or trainer_note or request_text,
        1200,
    )
    diagnosis["corrective_instruction"] = _trim(
        diagnosis.get("corrective_instruction")
        or expected_behavior
        or trainer_note,
        2000,
    )
    diagnosis["verification"] = _trim(
        diagnosis.get("verification"),
        1600,
    )
    diagnosis["can_learn_as_rule"] = (
        diagnosis.get("can_learn_as_rule") is True
    )
    diagnosis["needs_code_fix"] = (
        diagnosis.get("needs_code_fix") is True
    )

    rule = None
    if (
        actor_role == "trainer"
        and diagnosis["can_learn_as_rule"]
        and not diagnosis["needs_code_fix"]
        and diagnosis["corrective_instruction"]
    ):
        rule = save_training_rule(
            category=category,
            trigger=diagnosis["trigger"],
            instruction=diagnosis["corrective_instruction"],
            example=(
                f"요청: {request_text}\n"
                f"잘못된 응답: {assistant_response}\n"
                f"훈련사: {trainer_note}\n"
                f"원하는 동작: {expected_behavior}"
            )[:7000],
            source="live_trainer",
            confidence=0.95,
        )

    scenario = _record_scenario(
        category=category,
        request_text=request_text,
        assistant_response=assistant_response,
        trainer_note=trainer_note,
        diagnosis=diagnosis,
        actor_role=actor_role,
    )
    learned_rules = [rule.id] if rule is not None else []
    run = TrainingRun.objects.create(
        scenario=scenario,
        mode=(
            "live_trainer"
            if actor_role == "trainer"
            else "live_user_feedback"
        ),
        transcript=[
            {"role": "user", "content": request_text},
            {"role": "assistant", "content": assistant_response},
            {
                "role": "trainer",
                "content": {
                    "note": trainer_note,
                    "expected_behavior": expected_behavior,
                },
            },
            {"role": "diagnostic", "content": diagnosis},
        ],
        score=0,
        mistakes=[diagnosis["root_cause"]],
        learned_rules=learned_rules,
    )

    if actor_role != "trainer":
        status = "user_feedback_candidate"
        message = (
            "사용자 교정 의견을 학습 후보로 저장했어요. "
            "전역 규칙에는 즉시 적용하지 않습니다."
        )
    elif rule is not None:
        status = "learned"
        message = "원인을 분석했고 재발 방지 규칙을 즉시 학습에 반영했어요."
    elif diagnosis["needs_code_fix"]:
        status = "code_fix_required"
        message = (
            "원인을 분석해 실전 훈련 사례로 저장했어요. "
            "이 문제는 대화 규칙보다 코드·데이터 흐름 보완이 필요해요."
        )
    else:
        status = "diagnosed"
        message = "원인을 분석해 실전 훈련 사례로 저장했어요."

    return {
        "status": status,
        "message": message,
        "run_id": run.id,
        "scenario_id": scenario.id,
        "rule_id": rule.id if rule is not None else None,
        "learned": rule is not None,
        "actor_role": actor_role,
        "diagnosis": diagnosis,
    }
