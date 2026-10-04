from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .services.openai_service import (
    get_openai_status,
    test_openai_connection,
)


def _request_api_key(request):
    return str(
        request.headers.get("X-OpenAI-API-Key", "")
    ).strip()


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
            **get_openai_status(
                _request_api_key(request)
            ),
        }
    )


@api_view(["POST"])
def openai_save(request):
    return Response(
        {
            "ok": False,
            "message": (
                "API Key는 서버에 저장하지 않습니다. "
                "최신 ARABA 앱의 MY 화면에서 기기에 저장하세요."
            ),
        },
        status=status.HTTP_410_GONE,
    )


@api_view(["POST"])
def openai_test(request):
    try:
        result = test_openai_connection(
            _request_api_key(request)
        )

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

        mission = create_mission(
            user_request,
            _request_api_key(request),
        )

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
