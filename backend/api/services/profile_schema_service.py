SCHEMA_VERSION = "2026-10-07-v1"


USER_SIGNUP_SCHEMA = {
    "schema_id": "araba.user.signup.v1",
    "version": SCHEMA_VERSION,
    "principle": "가입에 꼭 필요한 정보와 개인화 정보를 분리하고, 민감정보는 기본 가입에서 받지 않는다.",
    "required": [
        {
            "key": "display_name",
            "label": "이름 또는 닉네임",
            "type": "string",
            "purpose": "계정 표시와 사용자 호칭",
        },
        {
            "key": "login_identifier",
            "label": "로그인 식별자",
            "type": "string",
            "purpose": "이메일·휴대전화·소셜로그인 중 실제 인증수단 식별",
        },
        {
            "key": "terms_consent",
            "label": "이용약관 동의",
            "type": "boolean",
            "must_be": True,
        },
        {
            "key": "privacy_consent",
            "label": "개인정보 처리방침 동의",
            "type": "boolean",
            "must_be": True,
        },
    ],
    "optional_profile": [
        {
            "key": "home_region",
            "label": "기본 생활지역",
            "type": "string",
            "purpose": "지역 검색 기본값",
        },
        {
            "key": "preferred_search_radius_km",
            "label": "기본 검색 반경",
            "type": "number",
            "unit": "km",
        },
        {
            "key": "preferred_contact_channel",
            "label": "알림 선호수단",
            "type": "enum",
            "options": ["push", "sms", "email", "none"],
        },
        {
            "key": "language",
            "label": "기본 언어",
            "type": "string",
            "default": "ko-KR",
        },
        {
            "key": "default_preferences",
            "label": "자주 쓰는 검색 선호조건",
            "type": "object",
            "examples": [
                "주차 우선",
                "가까운 곳 우선",
                "늦게까지 영업",
            ],
        },
    ],
    "do_not_collect_by_default": [
        "주민등록번호",
        "건강·질병정보",
        "정치·종교 등 민감정보",
        "카드번호 원문",
        "계좌 비밀번호",
        "외부 서비스 API 비밀키 원문",
    ],
    "runtime_context": {
        "description": "가입정보가 아니라 매 요청에서 필요할 때만 쓰는 정보",
        "fields": [
            "현재 위치",
            "이번 요청의 예산",
            "이번 요청의 시간대",
            "이번 요청의 특별조건",
        ],
    },
}


BUSINESS_SIGNUP_SCHEMA = {
    "schema_id": "araba.business.signup.v1",
    "version": SCHEMA_VERSION,
    "principle": "사업자 기본정보, 실제 운영데이터, 거래조건, Agent 권한을 분리해 저장한다.",
    "owner_account": {
        "required": [
            "owner_name",
            "login_identifier",
            "owner_role",
            "terms_consent",
            "privacy_consent",
        ],
        "optional": [
            "contact_phone",
            "contact_email",
        ],
    },
    "business_identity": {
        "required": [
            "business_name",
            "business_category",
            "business_address",
            "business_phone",
        ],
        "recommended": [
            "business_registration_number",
            "road_address",
            "latitude",
            "longitude",
            "homepage_url",
            "place_urls",
        ],
    },
    "operations": {
        "fields": [
            "opening_hours",
            "holiday_rules",
            "parking_available",
            "parking_text",
            "service_area",
            "visit_rules",
        ],
    },
    "service_catalog": {
        "item_schema": {
            "service_id": "string",
            "name": "string",
            "description": "string",
            "base_price": "number|null",
            "currency": "string",
            "duration_minutes": "integer|null",
            "bookable": "boolean",
            "stock_managed": "boolean",
            "tags": "array[string]",
        }
    },
    "availability": {
        "fields": [
            "available_slots",
            "capacity_rules",
            "lead_time_minutes",
            "same_day_booking",
            "reservation_channel",
        ],
    },
    "policies": {
        "fields": [
            "cancellation_policy",
            "refund_policy",
            "deposit_policy",
            "no_show_policy",
            "age_or_eligibility_rules",
        ],
    },
    "agent_authority": {
        "description": "Business AI가 사람 승인 없이 할 수 있는 범위를 명시",
        "fields": [
            "can_answer_factual_questions",
            "can_offer_discount",
            "max_discount_percent",
            "min_allowed_price",
            "can_confirm_booking",
            "booking_value_limit",
            "can_change_time",
            "can_cancel_booking",
            "requires_human_approval_for",
            "prohibited_actions",
        ],
    },
    "negotiation": {
        "description": "AI 간 자동 협상에 사용할 경계값",
        "fields": [
            "negotiable_fields",
            "price_floor",
            "price_ceiling",
            "discount_ceiling_percent",
            "allowed_bundles",
            "time_flexibility_minutes",
            "auto_accept_rules",
        ],
    },
    "evidence": {
        "item_schema": {
            "field": "string",
            "value": "any",
            "source_type": "business_input|website|platform|api|document|staff_verified",
            "source_url": "string|null",
            "verified_at": "datetime|null",
            "expires_at": "datetime|null",
            "confidence": "high|medium|low",
        }
    },
    "integrations": {
        "description": "예약·POS·캘린더·결제 연결정보. 비밀키 원문은 별도 Secret 저장소 사용.",
        "fields": [
            "provider",
            "connection_id",
            "capabilities",
            "status",
        ],
    },
    "agent_protocol_mapping": {
        "description": "외부 Agent/커머스 프로토콜과 매핑 가능한 공통 필드",
        "fields": [
            "merchant",
            "catalog",
            "offer",
            "availability",
            "policy",
            "agent_authority",
            "evidence",
        ],
    },
}


ARABA_BUSINESS_DATA_SCHEMA = {
    "schema_id": "araba.business.data.v1",
    "version": SCHEMA_VERSION,
    "top_level": [
        "identity",
        "operations",
        "services",
        "availability",
        "policies",
        "agent_authority",
        "negotiation",
        "evidence",
        "integrations",
        "updated_at",
    ],
    "source_of_truth_rule": (
        "사업자가 직접 입력하거나 연결 API로 확인된 값이 원본이며, "
        "LLM은 비정형 입력을 이 구조로 변환하되 출처 없는 값을 사실로 확정하지 않는다."
    ),
}


def signup_schema_catalog():
    return {
        "version": SCHEMA_VERSION,
        "user_signup": USER_SIGNUP_SCHEMA,
        "business_signup": BUSINESS_SIGNUP_SCHEMA,
        "business_data": ARABA_BUSINESS_DATA_SCHEMA,
    }
