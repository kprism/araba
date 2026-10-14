"""Merchant pilot API: secure account sessions and claims on existing ARABA Business rows.

Role preview in the admin test app never grants any server-side privileges.
Unverified claims may save drafts but NEVER mutate public Business records.
"""
import hashlib
import hmac
import re

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .models import Business, BusinessClaim, BusinessFact

User = get_user_model()
AUTHENTICATION = [TokenAuthentication, SessionAuthentication]
BUSINESS_EDITABLE = ("name", "category", "address", "phone", "opening_hours", "parking", "prices")
BUSINESS_BASIC = ("name", "category", "address", "phone")


def _error(message, code=400):
    return Response({"ok": False, "message": message}, status=code)


def _username(value):
    return str(value or "").strip().lower()


def _claim_json(record):
    business = record.business
    return {
        "id": record.id,
        "business_id": business.id,
        "business_name": business.name,
        "business_address": business.address,
        "business_category": business.category,
        "business_phone": business.phone,
        "status": record.status,
        "owner_name": record.owner_name,
        "registration_last4": record.registration_last4,
        "contact_phone": record.contact_phone,
        "proposed_info": record.proposed_info or {},
        "extra_information": record.extra_information,
        "agent_instructions": record.agent_instructions,
        "review_note": record.review_note,
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def username_available(request):
    username = _username(request.query_params.get("username"))
    if not re.fullmatch(r"[a-z0-9_.-]{4,30}", username):
        return _error("아이디는 영문 소문자·숫자·._-를 사용해 4~30자로 입력해주세요.")
    return Response({
        "ok": True,
        "available": not User.objects.filter(username__iexact=username).exists(),
    })


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def signup(request):
    username = _username(request.data.get("username"))
    password = str(request.data.get("password") or "")
    confirm = str(request.data.get("password_confirm") or "")
    if not re.fullmatch(r"[a-z0-9_.-]{4,30}", username):
        return _error("아이디는 영문 소문자·숫자·._-를 사용해 4~30자로 입력해주세요.")
    if password != confirm:
        return _error("비밀번호와 확인 입력이 일치하지 않습니다.")
    if request.data.get("terms_consent") is not True or request.data.get("privacy_consent") is not True:
        return _error("필수 약관 및 개인정보 처리 동의가 필요합니다.")
    if User.objects.filter(username__iexact=username).exists():
        return _error("이미 사용 중인 아이디입니다.", 409)
    user = User(username=username)
    try:
        password_validation.validate_password(password, user)
    except ValidationError as exc:
        return _error(" ".join(exc.messages))
    try:
        with transaction.atomic():
            user.set_password(password)
            user.save()
            token = Token.objects.create(user=user)
    except IntegrityError:
        return _error("이미 사용 중인 아이디입니다.", 409)
    return Response({
        "ok": True, "token": token.key,
        "user": {"id": user.id, "username": user.username, "is_staff": False},
        "notice": "계정이 생성됐습니다. 사업장 수정 권한은 소유권 심사 후 활성화됩니다.",
    }, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def login(request):
    username = _username(request.data.get("username"))
    password = str(request.data.get("password") or "")
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return _error("아이디 또는 비밀번호를 확인해주세요.", 401)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({
        "ok": True, "token": token.key,
        "user": {"id": user.id, "username": user.username, "is_staff": user.is_staff},
    })


@api_view(["GET"])
@authentication_classes(AUTHENTICATION)
@permission_classes([IsAuthenticated])
def account(request):
    claims = BusinessClaim.objects.filter(user=request.user).select_related("business").order_by("-created_at")
    return Response({
        "ok": True,
        "user": {"id": request.user.id, "username": request.user.username, "is_staff": request.user.is_staff},
        "claims": [_claim_json(item) for item in claims[:50]],
    })


@api_view(["POST"])
@authentication_classes(AUTHENTICATION)
@permission_classes([IsAuthenticated])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def search_existing_business(request):
    query = str(request.query_params.get("q") or "").strip()
    if len(query) < 2 or len(query) > 70:
        return _error("상호명이나 지역을 2~70자로 검색해 주세요.")
    terms = query.split()
    qs = Business.objects.filter(active=True)
    for term in terms[:4]:
        qs = qs.filter(
            Q(name__icontains=term) |
            Q(normalized_name__icontains=term) |
            Q(address__icontains=term) |
            Q(road_address__icontains=term)
        )
    rows = qs.order_by("name", "id").values(
        "id", "name", "category", "address", "road_address", "phone"
    )[:20]
    return Response({"ok": True, "businesses": list(rows)})


@api_view(["POST"])
@authentication_classes(AUTHENTICATION)
@permission_classes([IsAuthenticated])
def submit_claim(request):
    try:
        business_id = int(request.data.get("business_id"))
    except (ValueError, TypeError):
        return _error("기존 업체 목록에서 정확한 업체를 선택해주세요.")
    business = Business.objects.filter(id=business_id, active=True).first()
    if business is None:
        return _error("해당 업체를 찾지 못했습니다.", 404)
    owner_name = str(request.data.get("owner_name") or "").strip()
    digits = re.sub(r"[^0-9]", "", str(request.data.get("registration_number") or ""))
    contact = str(request.data.get("contact_phone") or "").strip()
    if len(owner_name) < 2 or len(owner_name) > 100:
        return _error("대표자 이름을 올바르게 입력해주세요.")
    if len(digits) != 10:
        return _error("사업자등록번호 10자리를 입력해주세요.")
    if len(contact) > 30:
        return _error("연락처가 너무 깁니다.")
    if BusinessClaim.objects.filter(business=business, status=BusinessClaim.STATUS_APPROVED).exists():
        return _error("이미 인증된 운영자가 있는 업체입니다. 운영자 권한을 요청하려면 고객센터에 문의해주세요.", 409)
    # Never persist or return the raw registration number.
    registration_hash = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        digits.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    try:
        claim = BusinessClaim.objects.create(
            user=request.user,
            business=business,
            owner_name=owner_name,
            registration_hash=registration_hash,
            registration_last4=digits[-4:],
            contact_phone=contact,
        )
    except IntegrityError:
        return _error("이 사업장에 대한 신청 이력이 있습니다. MY에서 신청 상태를 확인해주세요.", 409)
    return Response({
        "ok": True, "claim": _claim_json(claim),
        "notice": "사업장 관리권한을 신청했습니다. 인증 전까지 정보 수정은 초안으로만 저장됩니다.",
    }, status=201)


def _validate_proposed(raw):
    if not isinstance(raw, dict):
        raise ValueError("기본정보는 항목별 형식으로 입력해주세요.")
    result = {}
    for key in BUSINESS_EDITABLE:
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str):
            raise ValueError("기본정보는 텍스트로 입력해주세요.")
        value = value.strip()
        if len(value) > (240 if key == "name" else 1000):
            raise ValueError("기본정보 길이 제한을 초과했습니다.")
        result[key] = value
    return result


def _publish_official(claim):
    """Only run for verified owners; keep official edits separate from crawled facts."""
    business = Business.objects.select_for_update().get(pk=claim.business_id)
    info = dict(claim.proposed_info or {})
    for field in BUSINESS_BASIC:
        if info.get(field):
            setattr(business, field, info[field])
    # Keep name lookup consistent with the verified owner's new business name.
    business.normalized_name = re.sub(
        r"[^0-9a-zA-Z가-힣]", "", business.name.lower(),
    )[:240]
    snapshot = dict(business.snapshot or {})
    # Snapshot is returned by public search APIs. Keep private AI operating
    # instructions, discounts and internal claim IDs out of public records.
    snapshot["business_official"] = {
        "profile": info,
        "extra_information": claim.extra_information,
    }
    business.snapshot = snapshot
    business.save(update_fields=[*BUSINESS_BASIC, "normalized_name", "snapshot"])
    official_facts = {
        "extra_information": claim.extra_information,
        **info,
    }
    for key, value in official_facts.items():
        if value:
            BusinessFact.objects.update_or_create(
                business=business,
                key=key,
                source="business_official",
                defaults={"value": {"value": value}, "confidence": 1.0},
            )


@api_view(["GET", "PATCH"])
@authentication_classes(AUTHENTICATION)
@permission_classes([IsAuthenticated])
def claim_detail(request, claim_id):
    claim = BusinessClaim.objects.select_related("business").filter(
        id=claim_id, user=request.user,
    ).first()
    if claim is None:
        return _error("접근할 수 없는 사업장 신청입니다.", 404)
    if request.method == "GET":
        return Response({"ok": True, "claim": _claim_json(claim)})
    if claim.status == BusinessClaim.STATUS_REJECTED:
        return _error("거절된 신청은 수정할 수 없습니다.", 403)
    try:
        proposed = _validate_proposed(request.data.get("proposed_info", {}))
    except ValueError as exc:
        return _error(str(exc))
    extra = str(request.data.get("extra_information", "") or "")
    instructions = str(request.data.get("agent_instructions", "") or "")
    if len(extra) > 12000 or len(instructions) > 6000:
        return _error("추가정보 또는 AI 지침 입력 길이를 초과했습니다.")
    with transaction.atomic():
        claim = BusinessClaim.objects.select_for_update().get(pk=claim.id, user=request.user)
        claim.proposed_info = proposed
        claim.extra_information = extra
        claim.agent_instructions = instructions
        claim.save(update_fields=["proposed_info", "extra_information", "agent_instructions", "updated_at"])
        if claim.status == BusinessClaim.STATUS_APPROVED:
            _publish_official(claim)
    return Response({
        "ok": True, "claim": _claim_json(claim),
        "published": claim.status == BusinessClaim.STATUS_APPROVED,
        "message": (
            "인증된 사업장 정보를 반영했습니다."
            if claim.status == BusinessClaim.STATUS_APPROVED
            else "수정 초안을 저장했습니다. 소유권 인증 이후 실제 업체 DB에 반영됩니다."
        ),
    })
