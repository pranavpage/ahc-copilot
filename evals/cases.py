"""Eval case format. Cases live in evals/cases.yaml (owner: B)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from copilot.tools.visual import VisualType

ROOT = Path(__file__).resolve().parent.parent


class Turn(BaseModel):
    user_id: str
    message: str


class EvalCase(BaseModel):
    id: str
    question: str | None = None
    turns: list[Turn] | None = None        # multi-turn cases
    user_id: str = "U-201"                 # Michael Turner
    visual: VisualType | Literal["none"] | None = None
    must_include: list[str] = []
    must_not_include: list[str] = []
    rubric: str | None = None
    follows: list[str] = []                # IDs of cases that must run first

    @model_validator(mode="after")
    def one_of_question_or_turns(self):
        if (self.question is None) == (self.turns is None):
            raise ValueError(f"{self.id}: set exactly one of question / turns")
        return self


def load_cases(path: str | Path = "evals/cases.yaml") -> list[EvalCase]:
    """Parse the cases file. A relative path is relative to the repo root."""
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    return [EvalCase.model_validate(c) for c in yaml.safe_load(path.read_text()) or []]
