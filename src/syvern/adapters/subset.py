"""In-process SysML v2 *subset* parser + adapter (Path A).

A dependency-free, deterministic parser for a practical subset of the SysML v2
textual notation. It is NOT the authoritative Pilot — it covers the common
structural AND behavioral constructs well enough to give *real* Stage 0 (parse),
*real* element extraction, and a *real* intra-file Stage 1 (name resolution).

Supported member keywords (definition `... def Name` and usage `... name`):
    structural: part, attribute, item, port, connection, interface, constraint, calc
    behavioral: action, state, transition, succession, requirement
    plus: package (scope), import, connection ends (`end ...`), flow, connect,
          and `first ... then ...` successions.

Out of scope (honest limits): full KerML semantics and type checking
(`typecheck` always returns ok with 0 type errors), the standard library, and
exotic syntax. Constructs outside the subset are reported as parse errors.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from syvern.adapters.base import ParseResult, ResolveResult, TypecheckResult
from syvern.models import ElementSummary, ErrorDetail


VERSION = "subset-0.1.0"

# Member keywords that produce an element, mapped to the SYVERN element type.
KW_TYPES = {
    "part": "part",
    "attribute": "attribute",
    "item": "item",
    "port": "port",
    "connection": "connection",
    "interface": "interface",
    "action": "action",
    "state": "state",
    "requirement": "requirement",
    "constraint": "constraint",
    "calc": "calc",
}

# Tokens that may precede a member keyword and are simply skipped.
MODIFIERS = {
    "abstract", "variation", "ref", "in", "out", "inout", "entry", "exit", "do",
    "individual", "readonly", "derived", "ordered", "nonunique", "public",
    "private", "protected", "composite", "snapshot", "timeslice", "occurrence",
    "default", "redefinition",
}

# Reference relation operators / keywords (each is followed by a qualified name).
STRICT_REL = {":", ":>", "specializes", "subsets", "typed", "by", "defined"}
LOOSE_REL = {":>>", "redefines"}

PRIMITIVES = {
    "real", "integer", "boolean", "string", "natural", "rational", "complex",
    "number", "scalarvalues", "numericalvalue",
}

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<lc>//[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<op>:>>|::>|:>|::|\.\.)
  | (?P<punct>[{}\[\]();,])
  | (?P<colon>:)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<other>\S)
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass
class _Token:
    kind: str
    value: str
    line: int


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    line = 1
    for match in _TOKEN_RE.finditer(text):
        kind = match.lastgroup
        value = match.group()
        if kind in ("ws", "lc", "bc"):
            line += value.count("\n")
            continue
        tokens.append(_Token(kind or "other", value, line))
        line += value.count("\n")
    return tokens


@dataclass
class _ParseOutput:
    ok: bool
    errors: list[ErrorDetail]
    elements: list[ElementSummary]
    unresolved_refs: int


@dataclass
class _Parser:
    tokens: list[_Token]
    pos: int = 0
    scope: list[str] = field(default_factory=list)
    elements: list[tuple[str, str]] = field(default_factory=list)  # (type, qname)
    def_names: set[str] = field(default_factory=set)
    usage_names: set[str] = field(default_factory=set)
    full_qnames: set[str] = field(default_factory=set)
    strict_refs: list[str] = field(default_factory=list)
    loose_refs: list[str] = field(default_factory=list)
    errors: list[ErrorDetail] = field(default_factory=list)

    # --- token helpers ---
    def _peek(self) -> _Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self) -> _Token | None:
        token = self._peek()
        if token is not None:
            self.pos += 1
        return token

    def _at(self, value: str) -> bool:
        token = self._peek()
        return token is not None and token.value == value

    def _error(self, message: str) -> None:
        token = self._peek()
        line = token.line if token is not None else -1
        self.errors.append(
            ErrorDetail(stage="parse", code="SUBSET_SYNTAX_ERROR", message=message,
                        location=f"line:{line}" if line >= 0 else None)
        )

    # --- grammar ---
    def parse(self) -> None:
        self._members(top_level=True)
        if self.pos < len(self.tokens):
            self._error(f"unexpected token '{self.tokens[self.pos].value}'")

    def _members(self, top_level: bool) -> None:
        while True:
            token = self._peek()
            if token is None:
                if not top_level:
                    self._error("unexpected end of input: missing '}'")
                return
            if token.value == "}":
                if top_level:
                    self._error("unexpected '}'")
                    self.pos += 1
                    continue
                return
            if not self._member():
                # error recovery: skip to next ';' or '}' so we can find more issues
                self._recover()

    def _member(self) -> bool:
        # skip leading modifiers
        while True:
            token = self._peek()
            if token is None:
                return False
            if token.kind == "id" and token.value in MODIFIERS and not self._next_is_relation(1):
                self.pos += 1
                continue
            break

        token = self._peek()
        if token is None or token.kind != "id":
            if token is not None:
                self._error(f"unexpected token '{token.value}'")
            return False

        keyword = token.value
        if keyword == "package":
            return self._package()
        if keyword == "import":
            return self._import()
        if keyword == "end":
            return self._end_member()
        if keyword in ("transition", "succession"):
            return self._transition(keyword)
        if keyword == "first":
            return self._succession_clause()
        if keyword == "flow":
            return self._flow()
        if keyword == "connect":
            return self._connect()
        if keyword in KW_TYPES:
            return self._typed_member(keyword)
        self._error(f"unexpected keyword '{keyword}'")
        return False

    def _next_is_relation(self, offset: int) -> bool:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return False
        return self.tokens[idx].value in STRICT_REL | LOOSE_REL

    def _package(self) -> bool:
        self.pos += 1  # 'package'
        name = self._qname()
        if name is None:
            self._error("expected package name")
            return False
        segment = name.split("::")[-1].lower()
        self.scope.append(segment)
        ok = True
        if self._at("{"):
            self.pos += 1
            self._members(top_level=False)
            if self._at("}"):
                self.pos += 1
            else:
                self._error("expected '}' to close package")
                ok = False
        elif self._at(";"):
            self.pos += 1
        else:
            self._error("expected '{' or ';' after package")
            ok = False
        self.scope.pop()
        return ok

    def _import(self) -> bool:
        self.pos += 1  # 'import'
        # consume qualified name possibly ending in ::*
        while True:
            token = self._peek()
            if token is None:
                break
            if token.value == ";":
                self.pos += 1
                return True
            self.pos += 1
        self._error("expected ';' after import")
        return False

    def _typed_member(self, keyword: str) -> bool:
        self.pos += 1  # keyword
        is_def = False
        if self._at("def"):
            self.pos += 1
            is_def = True
        name = self._qname()
        emitted_type = KW_TYPES[keyword]
        if name is not None:
            segment = name.split("::")[-1].lower()
            qname = "::".join([*self.scope, segment])
            self.elements.append((emitted_type, qname))
            self.full_qnames.add(qname)
            (self.def_names if is_def else self.usage_names).add(segment)
            self._relations()
            return self._tail(scope_segment=segment)
        # unnamed usage (e.g. `:>> redefinition`) — still parse relations/tail
        self._relations()
        return self._tail(scope_segment=None)

    def _end_member(self) -> bool:
        self.pos += 1  # 'end'
        # optional inner keyword (e.g. `end part source : Pump`)
        inner = self._peek()
        if inner is not None and inner.value in KW_TYPES:
            self.pos += 1
        name = self._qname()
        segment = name.split("::")[-1].lower() if name else None
        if segment is not None:
            self.usage_names.add(segment)
        self._relations()
        return self._tail(scope_segment=None)  # ends are not emitted as elements

    def _transition(self, keyword: str) -> bool:
        self.pos += 1  # 'transition' | 'succession'
        # optional name (only if followed by 'first'/relation, not a ref keyword)
        name = None
        token = self._peek()
        if token is not None and token.kind == "id" and token.value not in ("first",):
            name = token.value
            self.pos += 1
        if name is not None:
            segment = name.lower()
            qname = "::".join([*self.scope, segment])
            self.elements.append(("transition", qname))
            self.full_qnames.add(qname)
            self.usage_names.add(segment)
        return self._transition_clause()

    def _succession_clause(self) -> bool:
        return self._transition_clause()

    def _transition_clause(self) -> bool:
        # expect: first <ref> [accept/if/...] then <ref> [do ...] ;
        if self._at("first"):
            self.pos += 1
            ref = self._qname()
            if ref:
                self.loose_refs.append(ref)
        # consume until 'then', skipping accept/if/guards
        while True:
            token = self._peek()
            if token is None or token.value in (";", "}"):
                break
            if token.value == "then":
                self.pos += 1
                ref = self._qname()
                if ref:
                    self.loose_refs.append(ref)
                break
            self.pos += 1
        return self._consume_to_semicolon()

    def _flow(self) -> bool:
        self.pos += 1  # 'flow'
        token = self._peek()
        if token is not None and token.kind == "id" and token.value not in ("from",):
            segment = token.value.lower()
            qname = "::".join([*self.scope, segment])
            self.elements.append(("flow", qname))
            self.full_qnames.add(qname)
            self.usage_names.add(segment)
            self.pos += 1
        # consume from/to refs loosely
        while True:
            token = self._peek()
            if token is None or token.value in (";", "}"):
                break
            if token.value in ("from", "to"):
                self.pos += 1
                ref = self._qname()
                if ref:
                    self.loose_refs.append(ref)
                continue
            self.pos += 1
        return self._consume_to_semicolon()

    def _connect(self) -> bool:
        self.pos += 1  # 'connect'
        while True:
            token = self._peek()
            if token is None or token.value in (";", "}"):
                break
            if token.value == "to":
                self.pos += 1
                ref = self._qname()
                if ref:
                    self.loose_refs.append(ref)
                continue
            ref = self._qname()
            if ref:
                self.loose_refs.append(ref)
            else:
                self.pos += 1
        return self._consume_to_semicolon()

    def _relations(self) -> None:
        while True:
            token = self._peek()
            if token is None:
                return
            value = token.value
            if value in (":", ":>", "specializes", "subsets"):
                self.pos += 1
                ref = self._qname()
                if ref:
                    self.strict_refs.append(ref)
                continue
            if value in (":>>", "redefines"):
                self.pos += 1
                ref = self._qname()
                if ref:
                    self.loose_refs.append(ref)
                continue
            return

    def _tail(self, scope_segment: str | None) -> bool:
        # optional multiplicity
        if self._at("["):
            if not self._skip_brackets():
                return False
        # relations may also appear after multiplicity
        self._relations()
        if self._at("{"):
            self.pos += 1
            if scope_segment is not None:
                self.scope.append(scope_segment)
            self._members(top_level=False)
            if scope_segment is not None:
                self.scope.pop()
            if self._at("}"):
                self.pos += 1
                return True
            self._error("expected '}'")
            return False
        if self._at(";"):
            self.pos += 1
            return True
        self._error("expected ';' or '{' after member")
        return False

    def _skip_brackets(self) -> bool:
        depth = 0
        while True:
            token = self._peek()
            if token is None:
                self._error("unterminated '['")
                return False
            self.pos += 1
            if token.value == "[":
                depth += 1
            elif token.value == "]":
                depth -= 1
                if depth == 0:
                    return True

    def _consume_to_semicolon(self) -> bool:
        while True:
            token = self._peek()
            if token is None:
                self._error("expected ';'")
                return False
            if token.value == ";":
                self.pos += 1
                return True
            if token.value == "}":
                self._error("expected ';'")
                return False
            self.pos += 1

    def _recover(self) -> None:
        while True:
            token = self._peek()
            if token is None:
                return
            self.pos += 1
            if token.value == ";":
                return
            if token.value == "}":
                self.pos -= 1
                return

    def _qname(self) -> str | None:
        token = self._peek()
        if token is None or token.kind != "id":
            return None
        parts = [token.value]
        self.pos += 1
        while self._at("::"):
            self.pos += 1
            nxt = self._peek()
            if nxt is None or nxt.kind != "id":
                break
            parts.append(nxt.value)
            self.pos += 1
        return "::".join(parts)

    # --- resolution ---
    def resolve_count(self) -> int:
        unresolved = 0
        for ref in self.strict_refs:
            if not self._resolves(ref, strict=True):
                unresolved += 1
        for ref in self.loose_refs:
            if not self._resolves(ref, strict=False):
                unresolved += 1
        return unresolved

    def _resolves(self, ref: str, strict: bool) -> bool:
        full = ref.lower()
        last = full.split("::")[-1]
        if last in PRIMITIVES:
            return True
        if full in self.full_qnames:
            return True
        if last in self.def_names:
            return True
        if not strict and last in self.usage_names:
            return True
        return False


def parse_subset(text: str) -> _ParseOutput:
    parser = _Parser(tokens=_tokenize(text))
    if not parser.tokens:
        return _ParseOutput(
            ok=False,
            errors=[ErrorDetail(stage="parse", code="SUBSET_EMPTY_INPUT", message="empty input")],
            elements=[],
            unresolved_refs=0,
        )
    parser.parse()
    ok = not parser.errors
    elements = (
        [ElementSummary(type=t, qualified_name=q) for (t, q) in parser.elements] if ok else []
    )
    unresolved = parser.resolve_count() if ok else 0
    return _ParseOutput(ok=ok, errors=parser.errors, elements=elements, unresolved_refs=unresolved)


class SubsetPilotAdapter:
    """ValidatorAdapter backed by the in-process subset parser (no JVM)."""

    name = "subset-pilot"

    def __init__(self) -> None:
        self._local = threading.local()

    def _output(self, text: str) -> _ParseOutput:
        if getattr(self._local, "text", None) != text:
            self._local.output = parse_subset(text)
            self._local.text = text
        return self._local.output

    def parse(self, text: str) -> ParseResult:
        output = self._output(text)
        return ParseResult(ok=output.ok, errors=output.errors, element_summary=output.elements)

    def resolve(self, text: str) -> ResolveResult:
        output = self._output(text)
        return ResolveResult(ok=output.unresolved_refs == 0, unresolved_refs=output.unresolved_refs)

    def typecheck(self, text: str) -> TypecheckResult:
        # The subset parser has no KerML semantics; typecheck is a no-op pass.
        return TypecheckResult(ok=True, type_errors=0)

    def fingerprint(self) -> str:
        return f"subset@{VERSION}"
