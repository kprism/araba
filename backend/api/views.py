from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .services.openai_service import (
    get_openai_status,
    save_api_key,
    test_openai_connection,
)


@api_view(["GET"])
def health(request):
    return Response(
        {
            "ok": True,
            "service": "ARABA API",
        }
    )


@api_view(["GET"])
def openai_status(request):
    return Response(
        {
            "ok": True,
            **get_openai_status(),
        }
    )


@api_view(["POST"])
def openai_save(request):
    try:
        api_key = str(
            request.data.get("api_key", "")
        ).strip()

        masked = save_api_key(api_key)

        return Response(
            {
                "ok": True,
                "configured": True,
                "masked": masked,
                "message": (
                    "OpenAI API Key가 서버에 저장되었습니다."
                ),
            }
        )

    except ValueError as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
def openai_test(request):
    try:
        result = test_openai_connection()

        return Response(
            {
                "ok": True,
                **result,
                "message": "OpenAI 연결에 성공했습니다.",
            }
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "connected": False,
                "message": f"OpenAI 연결 실패: {exc}",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
def mission_create(request):
    from .services.mission_service import create_mission

    try:
        user_request = str(
            request.data.get("request", "")
        ).strip()

        mission = create_mission(user_request)

        return Response(
            {
                "ok": True,
                "mission": mission,
            }
        )

    except ValueError as exc:
        return Response(
            {
                "ok": False,
                "message": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "message": (
                    "Mission 생성 중 오류가 발생했습니다: "
                    f"{exc}"
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
