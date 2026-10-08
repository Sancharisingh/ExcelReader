from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class Workflow(BaseModel):
    id: str
    name: str
    description: str = ""
    inputs: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    expected_output: str = ""


class StepTrace(BaseModel):
    step: str
    status: str
    tool: str | None = None
    detail: str


class AgentResult(BaseModel):
    selected_workflow: str | None
    selection_reason: str
    steps_executed: list[StepTrace] = Field(default_factory=list)
    final_output: str
    data: dict[str, Any] = Field(default_factory=dict)
