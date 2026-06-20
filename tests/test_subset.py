from pathlib import Path

from syvern.adapters.subset import SubsetPilotAdapter, parse_subset
from syvern.alignment import load_alignment_cases
from syvern.pipeline import ValidationPipeline


REAL_CORPUS = Path(__file__).resolve().parents[1] / "data" / "alignment" / "pilot_real_corpus.jsonl"


def _elements(text):
    return {(e.type, e.qualified_name) for e in parse_subset(text).elements}


def test_parses_structural_model_with_real_qualified_names():
    text = "package P { part def Vehicle { attribute mass; part engine : Engine; } part def Engine; }"
    output = parse_subset(text)

    assert output.ok is True
    assert _elements(text) == {
        ("part", "p::vehicle"),
        ("attribute", "p::vehicle::mass"),
        ("part", "p::vehicle::engine"),
        ("part", "p::engine"),
    }
    # the keyword 'def' is never mistaken for an element name (the old regex bug)
    assert all(name != "def" for _t, name in _elements(text))


def test_parses_behavior_state_machine():
    text = (
        "package SM {\n"
        "  state def Controller {\n"
        "    entry action initialize;\n"
        "    state idle;\n"
        "    state running;\n"
        "    transition startup first idle then running;\n"
        "  }\n"
        "}"
    )
    output = parse_subset(text)

    assert output.ok is True
    assert _elements(text) == {
        ("state", "sm::controller"),
        ("action", "sm::controller::initialize"),
        ("state", "sm::controller::idle"),
        ("state", "sm::controller::running"),
        ("transition", "sm::controller::startup"),
    }
    # transition targets (idle, running) resolve as in-scope usages
    assert output.unresolved_refs == 0


def test_parses_action_flow_with_successions_and_item_flow():
    text = (
        "package AF {\n"
        "  item def Data;\n"
        "  action def Pipeline {\n"
        "    action ingest;\n"
        "    action store;\n"
        "    flow stream from ingest to store;\n"
        "    first ingest then store;\n"
        "  }\n"
        "}"
    )
    output = parse_subset(text)

    assert output.ok is True
    assert ("flow", "af::pipeline::stream") in _elements(text)
    assert ("action", "af::pipeline::ingest") in _elements(text)
    assert output.unresolved_refs == 0


def test_resolves_intra_file_references():
    resolved = parse_subset("package P { part def Engine; part def Car { part e : Engine; } }")
    assert resolved.unresolved_refs == 0

    unresolved = parse_subset("package P { part def Car { part e : Engine; } }")
    assert unresolved.ok is True
    assert unresolved.unresolved_refs == 1  # Engine is never defined


def test_detects_syntax_errors():
    assert parse_subset("package P { part def V { attribute mass; }").ok is False  # missing brace
    assert parse_subset("package P { parts def V { } }").ok is False  # bad keyword
    assert parse_subset("package P { part def V { attribute a attribute b; } }").ok is False  # missing ;
    assert parse_subset("").ok is False  # empty


def test_typecheck_is_a_noop_pass():
    adapter = SubsetPilotAdapter()
    result = adapter.typecheck("package P { part def V { part x : NotAType; } }")
    assert result.ok is True
    assert result.type_errors == 0


def test_subset_parse_agrees_with_real_pilot_corpus():
    # The corpus is calibrated to the real Pilot; the subset's element sets differ
    # (simpler extraction) but its SYNTAX layer must agree with the authoritative
    # parser on what parses and what doesn't.
    cases = load_alignment_cases(REAL_CORPUS)
    adapter = SubsetPilotAdapter()
    disagreements = [c.case_id for c in cases if adapter.parse(c.text).ok != c.parse_ok]
    assert disagreements == []


class _TaggingAdapter:
    """Records parse calls and tags its element so we can tell which backend ran."""

    name = "tagging"

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.calls: list[str] = []

    def fingerprint(self) -> str:
        return f"tag@{self.tag}"

    def parse(self, text: str):
        from syvern.adapters.base import ParseResult
        from syvern.models import ElementSummary

        self.calls.append(text)
        return ParseResult(
            ok=True, errors=[], element_summary=[ElementSummary(type="part", qualified_name=f"m::{self.tag}")]
        )

    def resolve(self, text: str):
        from syvern.adapters.base import ResolveResult

        return ResolveResult(ok=True, unresolved_refs=0)

    def typecheck(self, text: str):
        from syvern.adapters.base import TypecheckResult

        return TypecheckResult(ok=True, type_errors=0)


def test_pipeline_runs_primary_for_online_and_authoritative_for_full():
    primary = _TaggingAdapter("online")
    authoritative = _TaggingAdapter("full")
    pipeline = ValidationPipeline(pilot_adapter=primary, authoritative_adapter=authoritative)

    pipeline.validate("part m.x", mode="online_reward")
    assert primary.calls == ["part m.x"]
    assert authoritative.calls == []

    pipeline.validate("part m.x", mode="full")
    assert authoritative.calls == ["part m.x"]  # full mode uses the authoritative L0
    assert primary.calls == ["part m.x"]  # primary untouched by the full run


def test_pipeline_red_line_broken_scores_below_valid_with_subset():
    pipeline = ValidationPipeline(pilot_adapter=SubsetPilotAdapter())

    valid = pipeline.validate("package P { part def Vehicle { attribute mass; } }", mode="online_reward")
    broken = pipeline.validate("package P { part def Vehicle { attribute mass; }", mode="online_reward")

    assert valid.stage.parse.ok is True
    assert broken.stage.parse.ok is False
    assert valid.meta.reward > broken.meta.reward
