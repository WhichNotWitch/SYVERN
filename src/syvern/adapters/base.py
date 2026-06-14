from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from syvern.models import ErrorDetail


@dataclass(frozen=True)
class ParseResult:
    ok: bool
    errors: list[ErrorDetail] = field(default_factory=list)


@dataclass(frozen=True)
class ResolveResult:
    ok: bool
    unresolved_refs: int = 0
    errors: list[ErrorDetail] = field(default_factory=list)


@dataclass(frozen=True)
class TypecheckResult:
    ok: bool
    type_errors: int = 0
    errors: list[ErrorDetail] = field(default_factory=list)


class ValidatorAdapter(Protocol):
    name: str

    def parse(self, text: str) -> ParseResult:
        raise NotImplementedError

    def resolve(self, text: str) -> ResolveResult:
        raise NotImplementedError

    def typecheck(self, text: str) -> TypecheckResult:
        raise NotImplementedError
