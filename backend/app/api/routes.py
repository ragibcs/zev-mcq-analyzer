"""API v1 routes: /analyze, /explain, /providers, /config."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.core.errors import InvalidRequestError, JevProviderError, LLMProviderError
from app.core.logging import get_logger
from app.schemas.api import (
    AnalyzeRequest,
    AnalyzeResponse,
    ConfigResponse,
    ExplainRequest,
    ExplainResponse,
    ProvidersResponse,
)
from app.services.analysis.service import AnalysisService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1")


def get_analysis_service(request: Request) -> AnalysisService:
    service = getattr(request.app.state, "analysis_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Jev analysis unavailable. No prediction was generated.",
        )
    return service


def _provider_names(request: Request) -> tuple[str, str]:
    """(decision_provider, llm_provider) names; safe when startup failed."""
    service = getattr(request.app.state, "analysis_service", None)
    decision = getattr(service, "_decision", None)
    llm = getattr(service, "_llm", None)
    return (
        decision.name if decision is not None else "jev",
        llm.name if llm is not None else "none",
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    service = get_analysis_service(request)
    try:
        result = await service.analyze(payload.question, payload.options)
    except JevProviderError as exc:
        # Spec §27: never invent a distribution; fail explicitly.
        status = 503 if exc.transient else 502
        logger.error(
            "Jev analysis failed",
            extra={"data": {"status_code": exc.status_code, "transient": exc.transient}},
        )
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return AnalyzeResponse(
        predicted_option=result.predicted_option,
        confidence=result.confidence,
        distribution=[p.model_dump() for p in result.distribution],
        provider=result.provider,
        model=result.model,
    )


@router.post("/explain", response_model=ExplainResponse)
async def explain(payload: ExplainRequest, request: Request) -> ExplainResponse:
    service = get_analysis_service(request)
    try:
        result = await service.explain(
            payload.question, payload.options, payload.jev_result
        )
    except LLMProviderError as exc:
        logger.error(
            "Explanation failed",
            extra={"data": {"provider": exc.provider}},
        )
        # 503 when not configured, 502 when the provider failed at runtime.
        status = 503 if exc.provider == "none" else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except InvalidRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ExplainResponse(
        summary=result.summary,
        per_option=result.per_option,
        provider=result.provider,
        model=result.model,
        restated_prediction=result.restated_prediction,
        restated_confidence_pct=result.restated_confidence_pct,
    )


@router.get("/providers", response_model=ProvidersResponse)
async def providers(request: Request) -> ProvidersResponse:
    decision_name, llm_name = _provider_names(request)
    return ProvidersResponse(
        decision_provider=decision_name,
        llm_provider=llm_name,
        llm_available=llm_name != "none",
    )


@router.get("/config", response_model=ConfigResponse)
async def config(request: Request) -> ConfigResponse:
    from app.core.config import get_settings

    settings = get_settings()
    decision_name, llm_name = _provider_names(request)
    return ConfigResponse(
        decision_provider=decision_name,
        llm_provider=llm_name,
        jev_model=settings.jev_model,
        limits={
            "max_question_chars": settings.max_question_chars,
            "max_option_chars": settings.max_option_chars,
            "max_options": settings.max_options,
        },
    )
