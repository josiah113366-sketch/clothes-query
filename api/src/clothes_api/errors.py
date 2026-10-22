"""API 오류. 응답은 {"error": 코드, "detail": 설명}이고 설명에는 PII·요청 값이 들어가지 않는다."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail


def not_found(code: str, detail: str = "") -> ApiError:
    return ApiError(404, code, detail)


def conflict(code: str, detail: str = "") -> ApiError:
    return ApiError(409, code, detail)


def unprocessable(code: str, detail: str = "") -> ApiError:
    return ApiError(422, code, detail)


def unavailable(code: str, detail: str = "") -> ApiError:
    return ApiError(503, code, detail)


def _body(code: str, detail: str) -> dict[str, str]:
    return {"error": code, "detail": detail}


def install_handlers(app: FastAPI) -> None:
    def _count(request: Request, code: str) -> None:
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.errors.labels(code).inc()

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, error: ApiError) -> JSONResponse:
        _count(request, error.code)
        return JSONResponse(_body(error.code, error.detail), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, error: RequestValidationError) -> JSONResponse:
        # FastAPI 기본 응답은 잘못된 값(input)을 그대로 돌려준다. 가입 요청에는 PII가 있으므로
        # 필드 위치와 오류 종류만 알린다.
        problems = []
        for item in error.errors():
            location = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
            # msg는 pydantic 기본 문구와 schemas.py의 문구뿐이다(입력값을 담지 않는다)
            problems.append(f"{location}: {item.get('type', 'invalid')} ({item.get('msg', '')})")
        _count(request, "VALIDATION_ERROR")
        return JSONResponse(_body("VALIDATION_ERROR", "; ".join(problems)), status_code=422)
