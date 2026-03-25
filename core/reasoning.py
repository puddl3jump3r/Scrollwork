"""Chain-of-thought reasoning engine."""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ThoughtType(str, Enum):
    OBSERVATION = "observation"
    ANALYSIS = "analysis"
    HYPOTHESIS = "hypothesis"
    PLAN = "plan"
    ACTION = "action"
    RESULT = "result"
    REFLECTION = "reflection"
    CONCLUSION = "conclusion"
    ERROR = "error"


@dataclass
class Thought:
    """A single thought in the reasoning chain."""

    type: ThoughtType
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class ReasoningChain:
    """A chain of thoughts for a single reasoning session."""

    thoughts: list[Thought] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed: bool = False

    def add(self, thought_type: ThoughtType, content: str, **metadata: Any) -> Thought:
        thought = Thought(type=thought_type, content=content, metadata=metadata)
        self.thoughts.append(thought)
        return thought

    def to_dict(self) -> dict[str, Any]:
        return {
            "thoughts": [t.to_dict() for t in self.thoughts],
            "started_at": self.started_at,
            "completed": self.completed,
            "duration": time.time() - self.started_at,
        }


REASONING_SYSTEM_PROMPT = """You are a reasoning engine. Think through problems step by step.

For each step in your reasoning, output a JSON object with:
- "type": one of "observation", "analysis", "hypothesis", "plan", "conclusion"
- "content": your thought for this step

Format your response as a JSON array of thought objects.
Think deeply and consider multiple angles before reaching conclusions.

Example:
[
  {"type": "observation", "content": "The user is asking about X"},
  {"type": "analysis", "content": "This involves Y and Z"},
  {"type": "hypothesis", "content": "The best approach would be..."},
  {"type": "plan", "content": "Step 1: ... Step 2: ..."},
  {"type": "conclusion", "content": "The answer is..."}
]"""


class ReasoningEngine:
    """Manages chain-of-thought reasoning processes."""

    def __init__(self) -> None:
        self.chains: list[ReasoningChain] = []
        self._current_chain: ReasoningChain | None = None

    def start_chain(self) -> ReasoningChain:
        """Start a new reasoning chain."""
        chain = ReasoningChain()
        self.chains.append(chain)
        self._current_chain = chain
        return chain

    def add_thought(
        self, thought_type: ThoughtType, content: str, **metadata: Any
    ) -> Thought | None:
        """Add a thought to the current chain."""
        if self._current_chain is None:
            self.start_chain()
        assert self._current_chain is not None
        return self._current_chain.add(thought_type, content, **metadata)

    def complete_chain(self) -> ReasoningChain | None:
        """Mark the current chain as complete."""
        if self._current_chain:
            self._current_chain.completed = True
            chain = self._current_chain
            self._current_chain = None
            return chain
        return None

    @property
    def current_chain(self) -> ReasoningChain | None:
        return self._current_chain

    def get_reasoning_prompt(self, task: str, context: str = "") -> str:
        """Generate a reasoning prompt for the LLM."""
        prompt = f"""Analyze this task carefully before acting.

Task: {task}
"""
        if context:
            prompt += f"\nContext:\n{context}\n"

        prompt += """
Think through this step by step:
1. What is being asked?
2. What information do I have?
3. What information do I need?
4. What are the possible approaches?
5. Which approach is best and why?
6. What are the concrete steps to execute?

Provide your analysis, then state your plan clearly."""

        return prompt

    def format_chain_for_context(self, chain: ReasoningChain | None = None) -> str:
        """Format a reasoning chain as context for the LLM."""
        chain = chain or self._current_chain
        if not chain or not chain.thoughts:
            return ""

        lines = ["[Reasoning Process]"]
        for thought in chain.thoughts:
            prefix = {
                ThoughtType.OBSERVATION: "Observed",
                ThoughtType.ANALYSIS: "Analyzed",
                ThoughtType.HYPOTHESIS: "Hypothesized",
                ThoughtType.PLAN: "Planned",
                ThoughtType.ACTION: "Acted",
                ThoughtType.RESULT: "Result",
                ThoughtType.REFLECTION: "Reflected",
                ThoughtType.CONCLUSION: "Concluded",
                ThoughtType.ERROR: "Error",
            }.get(thought.type, "Thought")
            lines.append(f"  {prefix}: {thought.content}")

        return "\n".join(lines)

    def get_reflection_prompt(self, action: str, result: str) -> str:
        """Generate a reflection prompt after an action."""
        return f"""Reflect on the result of this action:

Action taken: {action}
Result: {result}

Consider:
1. Did the action achieve its goal?
2. Were there any unexpected outcomes?
3. Should the plan be adjusted?
4. What was learned from this step?

Provide a brief reflection."""
