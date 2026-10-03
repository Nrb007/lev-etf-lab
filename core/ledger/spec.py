"""Hypothesis spec model (SPEC Section 7.1).

Every field of the pre-registered spec is required and unknown keys are rejected, so a spec cannot
carry pass/fail thresholds (those live in ``config/thresholds.yaml``) or silently misspell a field.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SpecError(ValueError):
    """The spec file is not valid YAML or does not satisfy the Section 7.1 model."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ParamGrid(_Strict):
    values: list = Field(min_length=1)


class Universe(_Strict):
    fund: str
    underlying: str | None = None
    research_universe: Literal["real", "synthetic_long"]
    leverage: float = 3
    # Extra feature columns: {column name: cache series name}, read from the train cache. This is
    # how a theory package hands its own series (e.g. a fund's NAV) to a signal, so that the
    # engine's leakage check sees them too.
    features: dict[str, str] = Field(default_factory=dict)


class HypothesisSpec(_Strict):
    id: str = Field(pattern=r"^H-\d{4}$")
    title: str
    mechanism: str
    universe: Universe
    signal_module: str
    params: dict[str, ParamGrid]
    benchmark: Literal["buy_and_hold"]
    primary_metric: Literal["sharpe"]
    registered_at: date
    notes_on_prior_trials: str

    @field_validator("title", "mechanism", "notes_on_prior_trials", "signal_module")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


def parse_spec(text: str | bytes, name: str = "spec") -> HypothesisSpec:
    try:
        return HypothesisSpec.model_validate(yaml.safe_load(text))
    except (ValueError, yaml.YAMLError) as exc:
        raise SpecError(f"{name}: invalid spec: {exc}") from exc
