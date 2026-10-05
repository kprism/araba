def build_research_simulation(mission):
    location = str(mission.get("location") or "요청 지역").strip()
    subject = str(mission.get("subject") or "요청 대상").strip()
    category = str(mission.get("category") or "기타").strip()

    businesses = [
        {
            "id": "mock-a",
            "name": f"{location} {subject} 가상 후보 A",
            "description": "조건 적합도가 높은 첫 번째 가상 후보입니다.",
            "image_url": None,
            "mock_call_result": "가상 통화 확인: 요청 조건에 맞고 빠른 대응이 가능한 것으로 설정했습니다.",
            "score": 92,
        },
        {
            "id": "mock-b",
            "name": f"{location} {subject} 가상 후보 B",
            "description": "가격 비교를 위한 두 번째 가상 후보입니다.",
            "image_url": None,
            "mock_call_result": "가상 통화 확인: 가격 경쟁력은 있으나 일부 조건은 추가 확인이 필요합니다.",
            "score": 86,
        },
        {
            "id": "mock-c",
            "name": f"{location} {subject} 가상 후보 C",
            "description": "대안으로 비교할 세 번째 가상 후보입니다.",
            "image_url": None,
            "mock_call_result": "가상 통화 확인: 예약 가능 시간 선택 폭이 넓은 것으로 설정했습니다.",
            "score": 81,
        },
    ]

    if category == "자동차":
        life_info = [
            "타이어나 정비 비용은 장착비, 휠밸런스, 폐기 비용이 별도인지 확인하면 실제 결제금액을 비교하기 쉽습니다.",
            "타이어는 규격뿐 아니라 제조주차와 재고 상태도 함께 확인하는 게 좋습니다.",
        ]
    elif category == "예약":
        life_info = [
            "예약 가능 여부뿐 아니라 취소 규정과 변경 가능 시간을 같이 확인하면 일정 변경 때 편합니다.",
            "예약 확정 전 최종 금액과 포함 항목을 한 번 더 확인하는 게 좋습니다.",
        ]
    elif category == "의료":
        life_info = [
            "진료 가능 시간과 함께 초진 접수 마감시간, 준비해야 할 서류가 있는지 확인하면 헛걸음을 줄일 수 있습니다.",
            "비급여 항목은 기관별 차이가 있을 수 있어 최종 비용을 직접 확인하는 게 좋습니다.",
        ]
    else:
        life_info = [
            "표시 가격만 보지 말고 추가비용과 당일 이용 가능 여부를 같이 확인하면 실제 선택이 쉬워집니다.",
            "후기보다 현재 재고, 운영시간, 예약 가능 여부처럼 변할 수 있는 정보는 직접 확인하는 게 안전합니다.",
        ]

    recommendation = {
        "business_id": businesses[0]["id"],
        "business_name": businesses[0]["name"],
        "summary": (
            f"현재 가상 테스트에서는 {businesses[0]['name']}을 1순위로 추천합니다. "
            "요청 조건에 가장 잘 맞는 것으로 설정된 후보입니다."
        ),
        "reason": "조건 적합도, 대응 가능성, 비교 점수를 종합한 가상 추천입니다.",
    }

    return {
        "mock": True,
        "businesses": businesses,
        "life_info": life_info,
        "recommendation": recommendation,
        "final_question": "이 업체로 예약을 진행할까요?",
        "actions": ["예약하기", "다른 후보 보기", "여기까지"],
    }
