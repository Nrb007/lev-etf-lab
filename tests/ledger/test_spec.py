from pathlib import Path

import pytest
import yaml

from core.ledger.spec import HypothesisSpec, SpecError, parse_spec
from tests.prereg_helpers import full_spec

TEMPLATE = Path(__file__).parents[2] / "hypotheses" / "H-0000_template.yaml"


def test_the_committed_template_is_a_valid_spec():
    spec = parse_spec(TEMPLATE.read_text(), TEMPLATE.name)
    assert spec.id == "H-0000" and spec.params["lookback"].values == [10, 20, 40]


def test_a_full_spec_validates():
    spec = HypothesisSpec.model_validate(full_spec())
    assert spec.benchmark == "buy_and_hold" and spec.primary_metric == "sharpe"


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "title",
        "mechanism",
        "universe",
        "signal_module",
        "params",
        "benchmark",
        "primary_metric",
        "registered_at",
        "notes_on_prior_trials",
    ],
)
def test_every_section_7_1_field_is_required(field):
    raw = full_spec()
    del raw[field]
    with pytest.raises(SpecError, match=field):
        parse_spec(yaml.safe_dump(raw))


def test_thresholds_are_not_part_of_the_spec():
    raw = full_spec(thresholds={"dsr": {"min": 0.5}})
    with pytest.raises(SpecError, match="thresholds"):
        parse_spec(yaml.safe_dump(raw))


@pytest.mark.parametrize(
    "override",
    [
        {"mechanism": "  "},
        {"notes_on_prior_trials": ""},
        {"id": "H-7"},
        {"params": {"window": {"values": []}}},
        {"primary_metric": "profit"},
        {"universe": {"fund": "TQQQ", "research_universe": "made_up"}},
    ],
)
def test_invalid_values_are_rejected(override):
    with pytest.raises(SpecError):
        parse_spec(yaml.safe_dump(full_spec(**override)))
