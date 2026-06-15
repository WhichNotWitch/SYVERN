from __future__ import annotations

import re
from typing import Any

from syvern.models import IntentSummary
from syvern.normalization import normalize_ws, token_count
from syvern.settings import SyvernSettings


def _normalize_phrase(value: str) -> str:
    return normalize_ws(value).lower()


def _phrase_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _string_list(intent_reference: dict[str, Any], key: str) -> list[str]:
    value = intent_reference.get(key)
    if not isinstance(value, list):
        return []
    return [_normalize_phrase(item) for item in value if isinstance(item, str) and normalize_ws(item)]


def _contains_phrase(text_key: str, phrase: str) -> bool:
    key = _phrase_key(phrase)
    return bool(key) and key in text_key


def _coverage_score(text_key: str, required: list[str]) -> float | None:
    if not required:
        return None
    matched = sum(1 for phrase in required if _contains_phrase(text_key, phrase))
    return 5.0 * matched / len(required)


def _correctness_score(text_key: str, forbidden: list[str]) -> float | None:
    if not forbidden:
        return None
    matches = sum(1 for phrase in forbidden if _contains_phrase(text_key, phrase))
    return max(0.0, 5.0 - 2.5 * matches)


def _overfit_underfit_score(text: str, required: list[str]) -> float | None:
    if not required:
        return None
    count = token_count(text)
    if count == 0:
        return 0.0
    score = 5.0
    if count < 3:
        score -= 2.0

    reference_terms = {
        term
        for phrase in required
        for term in re.findall(r"[a-z0-9]+", phrase.lower())
        if len(term) > 2
    }
    generated_terms = [term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2]
    if generated_terms and reference_terms:
        unrelated = sum(1 for term in generated_terms if term not in reference_terms)
        unrelated_ratio = unrelated / len(generated_terms)
        if unrelated_ratio > 0.75:
            score -= 1.5
    return max(0.0, min(5.0, score))


def _single_vote(text: str, intent_reference: dict[str, Any]) -> float | None:
    requirements = _string_list(intent_reference, "requirements")
    must_include = _string_list(intent_reference, "must_include")
    must_not_include = _string_list(intent_reference, "must_not_include")
    required = requirements + must_include
    text_key = _phrase_key(text)

    scores = [
        _coverage_score(text_key, required),
        _correctness_score(text_key, must_not_include),
        _overfit_underfit_score(text, required),
    ]
    evaluated_scores = [score for score in scores if score is not None]
    if not evaluated_scores:
        return None
    return sum(evaluated_scores) / len(evaluated_scores)


def evaluate_intent(text: str, intent_reference: dict[str, Any] | None, settings: SyvernSettings) -> IntentSummary:
    if not intent_reference:
        return IntentSummary()

    votes: list[float] = []
    for _ in range(settings.intent_vote_count):
        score = _single_vote(text, intent_reference)
        if score is None:
            return IntentSummary()
        votes.append(score)

    averaged = sum(votes) / len(votes)
    return IntentSummary(evaluated=True, score=max(0.0, min(5.0, averaged)), source="llm_judge")
