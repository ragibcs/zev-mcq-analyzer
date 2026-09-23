"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import JevAnalyzerError
from app.core.logging import configure_logging, get_logger
from app.core.security import (
    ApiKeyMiddleware,
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
)
from app.services.analysis.service import AnalysisService
from app.services.jev.factory import get_decision_provider
from app.services.llm.factory import get_llm_provider

logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Jev MCQ Confidence Analyzer",
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # ── Security middleware ────────────────────────────────────────────
    app.add_middleware(ApiKeyMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RateLimitMiddleware)

    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,  # explicit allow-list; no wildcard with auth
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key"],
            allow_credentials=False,
        )

    # ── Providers (fail fast on bad config) ────────────────────────────
    try:
        decision_provider = get_decision_provider()
        llm_provider = get_llm_provider()
        app.state.analysis_service = AnalysisService(decision_provider, llm_provider)
        logger.info(
            "Providers initialized",
            extra={
                "data": {
                    "decision": decision_provider.name,
                    "llm": llm_provider.name,
                }
            },
        )
    except Exception as exc:  # noqa: BLE001 — startup must not crash /health
        # Configuration errors must not take down /health; routes that need
        # providers will surface the error explicitly.
        app.state.analysis_service = None
        app.state.startup_error = str(exc)
        logger.error("Provider initialization failed", extra={"data": {"error": type(exc).__name__}})

    # ── Routes ─────────────────────────────────────────────────────────
    app.include_router(api_v1_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(JevAnalyzerError)
    async def app_error_handler(_request, exc: JevAnalyzerError):  # type: ignore[no-untyped-def]
        logger.error("Application error", extra={"data": {"error": type(exc).__name__}})
        return JSONResponse(
            status_code=500,
            content={"error": "Internal error.", "detail": None},
        )

    return app


app = create_app()
