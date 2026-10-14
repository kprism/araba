"""Explicit, reversible business visibility changes, restricted to Django staff.

Public research/upsert endpoints never remove or toggle saved Businesses.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .models import Business


@api_view(["POST"])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([IsAdminUser])
def update_business_visibility(request):
    data = request.data
    ids = data.get("ids")
    active = data.get("active")
    confirmation = data.get("confirmation")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 100
        or any(type(business_id) is not int or business_id <= 0 for business_id in ids)
        or len(set(ids)) != len(ids)
    ):
        return Response(
            {"ok": False, "message": "선택한 업체 ID는 중복 없는 정수 1~100개여야 합니다."},
            status=400,
        )
    if type(active) is not bool or confirmation != "SELECTED_ONLY":
        return Response(
            {"ok": False, "message": "대상 업체와 작업을 확인한 후 다시 요청해주세요."},
            status=400,
        )

    # The operation is all-or-nothing. Never silently affect a wider filter
    # or an unrelated search result. It preserves all Business and Fact rows.
    with transaction.atomic():
        businesses = list(Business.objects.select_for_update().filter(pk__in=ids))
        if len(businesses) != len(ids):
            return Response(
                {"ok": False, "message": "선택한 업체 중 존재하지 않는 항목이 있습니다."},
                status=404,
            )
        changed = []
        now = timezone.now().isoformat()
        for business in businesses:
            if business.active == active:
                continue
            old_active = business.active
            meta = dict(business.source_meta or {})
            audit = meta.get("admin_visibility_history")
            if not isinstance(audit, list):
                audit = []
            audit.append({
                "admin_user_id": request.user.pk,
                "changed_at": now,
                "from_active": old_active,
                "to_active": active,
            })
            meta["admin_visibility_history"] = audit[-30:]
            business.source_meta = meta
            business.active = active
            business.save(update_fields=["active", "source_meta"])
            changed.append(business.pk)

    return Response({
        "ok": True,
        "requested": len(ids),
        "changed": len(changed),
        "changed_ids": changed,
        "active": active,
        "message": (
            f"선택한 업체 중 {len(changed)}곳이 다시 활성화됐습니다."
            if active else f"선택한 업체 중 {len(changed)}곳을 목록에서 숨겼습니다. 비활성 필터에서 복원할 수 있습니다."
        ),
    })
