from django.contrib import admin, messages
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import BusinessClaim


@admin.register(BusinessClaim)
class BusinessClaimAdmin(admin.ModelAdmin):
    list_display = (
        "id", "business", "user", "owner_name", "registration_last4",
        "status", "created_at", "reviewed_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "business__name", "business__address", "user__username",
        "owner_name", "contact_phone",
    )
    readonly_fields = (
        "user", "business", "owner_name", "registration_hash",
        "registration_last4", "contact_phone", "created_at",
        "updated_at", "reviewed_by", "reviewed_at",
    )
    actions = ("approve_verified", "reject_claims")

    @admin.action(description="외부 서류·운영권 확인 완료: 관리권한 승인")
    def approve_verified(self, request, queryset):
        approved = 0
        for claim in queryset.select_related("business"):
            if claim.status == BusinessClaim.STATUS_APPROVED:
                continue
            try:
                with transaction.atomic():
                    current = BusinessClaim.objects.select_for_update().get(pk=claim.pk)
                    current.status = BusinessClaim.STATUS_APPROVED
                    current.reviewed_by = request.user
                    current.reviewed_at = timezone.now()
                    current.save(update_fields=[
                        "status", "reviewed_by", "reviewed_at", "updated_at"
                    ])
                    approved += 1
            except IntegrityError:
                self.message_user(
                    request,
                    f"{claim.business.name}: 이미 인증된 운영자가 있어 승인할 수 없습니다.",
                    level=messages.ERROR,
                )
        self.message_user(request, f"{approved}건을 인증 승인했습니다.", level=messages.INFO)

    @admin.action(description="관리권한 신청 거절·회수")
    def reject_claims(self, request, queryset):
        queryset.update(
            status=BusinessClaim.STATUS_REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, "선택한 신청을 거절 또는 회수했습니다.", level=messages.INFO)
