from pydantic import ValidationError

from syvern.adapters.stub import MontiCoreStubAdapter, PilotStubAdapter
from syvern.models import BatchValidateRequest, ElementSummary


def test_element_summary_trims_and_lowercases_fields():
    summary = ElementSummary(type=" Part ", qualified_name=" Vehicle.Engine ")

    assert summary.type == "part"
    assert summary.qualified_name == "vehicle.engine"


def test_element_summary_rejects_blank_fields():
    for payload in (
        {"type": "", "qualified_name": "vehicle.engine"},
        {"type": "part", "qualified_name": "   "},
    ):
        try:
            ElementSummary(**payload)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"Expected validation error for {payload}")


def test_batch_validate_request_rejects_empty_texts():
    try:
        BatchValidateRequest(texts=[], mode="online_reward")
    except ValidationError:
        pass
    else:
        raise AssertionError("Expected empty batch validation to fail")


def test_pilot_stub_extracts_normalized_element_summaries():
    result = PilotStubAdapter().parse("Part Vehicle.Engine attribute Mass connection power-link")

    assert result.ok is True
    assert [item.model_dump() for item in result.element_summary] == [
        {"type": "part", "qualified_name": "vehicle.engine"},
        {"type": "attribute", "qualified_name": "mass"},
        {"type": "connection", "qualified_name": "power-link"},
    ]


def test_parser_agreement_ignores_summary_order_but_counts_duplicates():
    pilot = PilotStubAdapter()
    monticore = MontiCoreStubAdapter()

    assert monticore.parser_agrees("attribute mass part Engine attribute mass", pilot) is True
    assert monticore.parser_agrees("part Engine summary_disagreement", pilot) is False


def test_parse_failures_return_empty_element_summary():
    result = PilotStubAdapter().parse("syntax_error part A")

    assert result.ok is False
    assert result.element_summary == []
