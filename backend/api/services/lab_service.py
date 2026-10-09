from api.models import LabCase


def serialize_lab_case(case):
    return {
        "id": case.id,
        "actor_role": case.actor_role,
        "category": case.category,
        "input_source": case.input_source,
        "report_text": case.report_text,
        "request_text": case.request_text,
        "assistant_response": case.assistant_response,
        "root_cause_type": case.root_cause_type,
        "diagnosis": case.diagnosis,
        "repair_plan": case.repair_plan,
        "status": case.status,
        "training_run_id": case.training_run_id,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
    }


def list_lab_cases(*, status=None, limit=50):
    try:
        safe_limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        safe_limit = 50

    queryset = LabCase.objects.all()
    status_text = str(status or "").strip()
    if status_text:
        queryset = queryset.filter(status=status_text)

    cases = list(queryset[:safe_limit])
    return {
        "count": len(cases),
        "cases": [
            serialize_lab_case(case)
            for case in cases
        ],
    }
