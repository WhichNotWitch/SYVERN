from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI

from syvern.cache import CacheKey, InMemoryValidationCache
from syvern.models import (
    BatchMetaSummary,
    BatchValidateRequest,
    BatchValidateResponse,
    Mode,
    ValidateRequest,
    ValidateResponse,
)
from syvern.normalization import (
    intent_reference_identity,
    perturbation_identity,
    reference_identity,
    sha256_text,
)
from syvern.pipeline import ValidationPipeline
from syvern.robustness import aggregate_robustness
from syvern.settings import SyvernSettings


settings = SyvernSettings()
pipeline = ValidationPipeline(settings=settings)
validation_cache = InMemoryValidationCache()
app = FastAPI(title="SYVERN", version="0.1.0")


def _validate_with_cache(
    text: str,
    *,
    mode: Mode,
    reference: dict | None,
    perturbations: list[str] | None,
    intent_reference: dict | None,
) -> ValidateResponse:
    text_hash = sha256_text(text)
    key = CacheKey(
        text_hash=text_hash,
        validator_fingerprint=settings.validator_fingerprint,
        mode=mode,
        reference_id=reference_identity(reference),
        perturbation_id=perturbation_identity(perturbations),
        intent_reference_id=intent_reference_identity(intent_reference),
    )
    cached = validation_cache.get(key)
    if cached is not None:
        cached_payload = deepcopy(cached)
        cached_payload["meta"]["cache_hit"] = True
        return ValidateResponse.model_validate(cached_payload)

    response = pipeline.validate(
        text,
        mode=mode,
        reference=reference,
        perturbations=perturbations,
        intent_reference=intent_reference,
    )
    payload = response.model_dump(mode="json")
    payload["meta"]["cache_hit"] = False
    validation_cache.set(key, payload)
    return ValidateResponse.model_validate(payload)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/validate", response_model=ValidateResponse)
def validate(request: ValidateRequest) -> ValidateResponse:
    return _validate_with_cache(
        request.text,
        mode=request.mode,
        reference=request.reference,
        perturbations=request.perturbations,
        intent_reference=request.intent_reference,
    )


@app.post("/validate_batch", response_model=BatchValidateResponse)
def validate_batch(request: BatchValidateRequest) -> BatchValidateResponse:
    responses = [
        _validate_with_cache(
            text,
            mode=request.mode,
            reference=request.reference,
            perturbations=request.perturbations,
            intent_reference=request.intent_reference,
        )
        for text in request.texts
    ]
    metrics = aggregate_robustness(responses)
    return BatchValidateResponse(
        sample_count=len(responses),
        pass_at_k=metrics.pass_at_k,
        stable_at_k=metrics.stable_at_k,
        responses=responses,
        meta=BatchMetaSummary(
            mode=request.mode,
            validator_fingerprint=settings.validator_fingerprint,
        ),
    )
