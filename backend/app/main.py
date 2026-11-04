import secrets
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text

from app.api.routes import calendar, drafts, planning, profile
from app.config import Settings
from app.llm.client import LLMInvalidResponse, LLMRequestError, OpenAICompatibleClient
from app.llm.service import ModelOutputValidationError, PlanningLLMService
from app.persistence.db import create_database_engine, create_session_factory


def create_app(*, settings: Settings | None = None, session_factory=None, llm_service=None) -> FastAPI:
    settings = settings or Settings()
    if session_factory is None:
        engine = create_database_engine(settings.database_url)
        session_factory = create_session_factory(engine)
    if llm_service is None:
        llm_service = PlanningLLMService(OpenAICompatibleClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
        ))
    app = FastAPI(title="AI 日历 API")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.llm_service = llm_service

    @app.middleware("http")
    async def access_control(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        public = request.url.path in {"/healthz", "/readyz", "/openapi.json", "/docs", "/redoc"}
        if settings.app_mode == "deployed" and not public:
            supplied = request.headers.get("X-Access-Code", "")
            expected = settings.app_access_code or ""
            if not supplied or not secrets.compare_digest(supplied, expected):
                return JSONResponse(status_code=401, content={"error_code":"UNAUTHORIZED","message":"访问码无效","retryable":False,"request_id":request_id},headers={"X-Request-ID":request_id})
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    def error_response(request: Request, status_code: int, code: str, message: str, retryable: bool) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(status_code=status_code,content={"error_code":code,"message":message,"retryable":retryable,"request_id":request_id},headers={"X-Request-ID":request_id})

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        return error_response(request,422,"VALIDATION_ERROR","请求参数不符合接口要求",False)

    @app.exception_handler(ValidationError)
    async def model_validation_handler(request: Request, exc: ValidationError):
        return error_response(request,502,"MODEL_OUTPUT_INVALID","模型输出未通过结构校验",True)

    @app.exception_handler(ModelOutputValidationError)
    async def model_output_validation_handler(request: Request, exc: ModelOutputValidationError):
        return error_response(request,502,"MODEL_OUTPUT_INVALID","模型输出未通过结构校验",True)

    @app.exception_handler(LLMRequestError)
    @app.exception_handler(LLMInvalidResponse)
    async def llm_error_handler(request: Request, exc: Exception):
        return error_response(request,503,"MODEL_UNAVAILABLE","模型服务暂时不可用，请重试",True)

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        code = "VALIDATION_ERROR" if exc.status_code == 422 else "REQUEST_ERROR"
        return error_response(request,exc.status_code,code,str(exc.detail),False)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        return error_response(request,500,"INTERNAL_ERROR","服务内部错误",True)

    @app.get("/healthz", tags=["system"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    def readiness_check() -> dict[str, str]:
        with session_factory() as db:
            db.execute(text("SELECT 1"))
        return {"status":"ready"}

    app.include_router(planning.router)
    app.include_router(drafts.router)
    app.include_router(calendar.router)
    app.include_router(profile.router)

    return app
