"""Task planning and execution tracking."""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """A single step in a plan."""

    description: str
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    tools_needed: list[str] = field(default_factory=list)
    started_at: float | None = None
    completed_at: float | None = None

    def start(self) -> None:
        self.status = StepStatus.IN_PROGRESS
        self.started_at = time.time()

    def complete(self, result: str = "") -> None:
        self.status = StepStatus.COMPLETED
        self.result = result
        self.completed_at = time.time()

    def fail(self, error: str = "") -> None:
        self.status = StepStatus.FAILED
        self.result = error
        self.completed_at = time.time()

    def skip(self, reason: str = "") -> None:
        self.status = StepStatus.SKIPPED
        self.result = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "status": self.status.value,
            "result": self.result,
            "tools_needed": self.tools_needed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class Plan:
    """A multi-step plan for accomplishing a task."""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    mode: str = "plan"  # plan, build, or chat
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def current_step(self) -> PlanStep | None:
        for step in self.steps:
            if step.status == StepStatus.IN_PROGRESS:
                return step
        return None

    @property
    def next_step(self) -> PlanStep | None:
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                return step
        return None

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(
            1 for s in self.steps
            if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        )
        return done / len(self.steps)

    @property
    def is_complete(self) -> bool:
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.FAILED)
            for s in self.steps
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "mode": self.mode,
            "steps": [s.to_dict() for s in self.steps],
            "progress": self.progress,
            "is_complete": self.is_complete,
            "created_at": self.created_at,
        }

    def format_status(self) -> str:
        """Human-readable plan status."""
        lines = [f"Plan: {self.goal}", f"Progress: {self.progress:.0%}", ""]
        for i, step in enumerate(self.steps, 1):
            icon = {
                StepStatus.PENDING: "[ ]",
                StepStatus.IN_PROGRESS: "[>]",
                StepStatus.COMPLETED: "[x]",
                StepStatus.FAILED: "[!]",
                StepStatus.SKIPPED: "[-]",
            }[step.status]
            lines.append(f"  {icon} Step {i}: {step.description}")
            if step.result:
                lines.append(f"       Result: {step.result[:100]}")
        return "\n".join(lines)


PLAN_GENERATION_PROMPT = """You are a planning assistant. Create a detailed, actionable plan.

Given a goal, break it down into concrete steps. Each step should be:
- Specific and actionable
- Clear about what tools or actions are needed
- Ordered logically (dependencies first)

Respond with a JSON array of step objects:
[
  {{"description": "step description", "tools_needed": ["tool1", "tool2"]}},
  ...
]

Keep plans focused and practical. Aim for 3-8 steps for most tasks.
For complex tasks, break into more steps but keep each step atomic."""


BUILD_PLAN_PROMPT = """You are a software architect and builder. Create a build plan.

Given a project goal, create a detailed build plan with concrete implementation steps.
Consider:
- Architecture and design decisions
- File structure and organization
- Dependencies and tools needed
- Testing approach
- Implementation order (foundations first)

Respond with a JSON array of step objects:
[
  {{"description": "step description", "tools_needed": ["tool1", "tool2"]}},
  ...
]"""


class Planner:
    """Manages task planning and execution tracking."""

    def __init__(self) -> None:
        self.plans: list[Plan] = []
        self._current_plan: Plan | None = None

    def create_plan(
        self, goal: str, steps: list[dict[str, Any]], mode: str = "plan"
    ) -> Plan:
        """Create a new plan from parsed step definitions."""
        plan_steps = [
            PlanStep(
                description=s.get("description", ""),
                tools_needed=s.get("tools_needed", []),
            )
            for s in steps
        ]
        plan = Plan(goal=goal, steps=plan_steps, mode=mode)
        self.plans.append(plan)
        self._current_plan = plan
        return plan

    def advance_plan(self) -> PlanStep | None:
        """Move to the next step in the current plan."""
        if not self._current_plan:
            return None

        # Complete current step if in progress
        current = self._current_plan.current_step
        if current and current.status == StepStatus.IN_PROGRESS:
            current.complete()

        # Start next step
        next_step = self._current_plan.next_step
        if next_step:
            next_step.start()
            return next_step

        return None

    def complete_current_step(self, result: str = "") -> None:
        """Mark the current step as completed."""
        if self._current_plan and self._current_plan.current_step:
            self._current_plan.current_step.complete(result)

    def fail_current_step(self, error: str = "") -> None:
        """Mark the current step as failed."""
        if self._current_plan and self._current_plan.current_step:
            self._current_plan.current_step.fail(error)

    @property
    def current_plan(self) -> Plan | None:
        return self._current_plan

    def get_plan_context(self) -> str:
        """Get the current plan as context for the LLM."""
        if not self._current_plan:
            return "No active plan."
        return self._current_plan.format_status()

    def get_planning_prompt(self, mode: str = "plan") -> str:
        """Get the appropriate system prompt for plan generation."""
        if mode == "build":
            return BUILD_PLAN_PROMPT
        return PLAN_GENERATION_PROMPT
