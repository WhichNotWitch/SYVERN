from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI

from syvern.cache import CacheKey, InMemoryValidationCache
from syvern.models import ValidateRequest, ValidateResponse
from syvern.normalization import reference_identity, sha256_text
from syvern.pipeline import ValidationPipeline
from syvern.settings import SyvernSettings


settings = SyvernSettings()
pipeline = ValidationPipeline(settings=settings)
validation_cache = InMemoryValidationCache()
app = FastAPI(title="SYVERN", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/validate", response_model=ValidateResponse)
def validate(request: ValidateRequest) -> ValidateResponse:
    text_hash = sha256_text(request.text)
    key = CacheKey(
        text_hash=text_hash,
        validator_fingerprint=settings.validator_fingerprint,
        mode=request.mode,
        reference_id=reference_identity(request.reference),
    )
    cached = validation_cache.get(key)
    if cached is not None:
        cached_payload = deepcopy(cached)
        cached_payload["meta"]["cache_hit"] = True
        return ValidateResponse.model_validate(cached_payload)

    response = pipeline.validate(request.text, mode=request.mode)
    payload = response.model_dump(mode="json")
    payload["meta"]["cache_hit"] = False
    validation_cache.set(key, payload)
    return ValidateResponse.model_validate(payload)
