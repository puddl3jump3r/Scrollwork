"""Intelligent model selection based on task analysis."""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Model capability profiles based on common model name patterns
MODEL_PROFILES: dict[str, dict[str, Any]] = {
    "codellama": {"strengths": ["coding", "analysis"], "category": "code"},
    "deepseek-coder": {"strengths": ["coding", "analysis"], "category": "code"},
    "starcoder": {"strengths": ["coding"], "category": "code"},
    "codestral": {"strengths": ["coding", "analysis"], "category": "code"},
    "qwen2.5-coder": {"strengths": ["coding", "analysis"], "category": "code"},
    "llama3": {"strengths": ["reasoning", "general", "analysis"], "category": "general"},
    "llama3.1": {"strengths": ["reasoning", "general", "analysis", "coding"], "category": "general"},
    "llama3.2": {"strengths": ["reasoning", "general", "analysis"], "category": "general"},
    "llama3.3": {"strengths": ["reasoning", "general", "analysis", "coding"], "category": "general"},
    "mistral": {"strengths": ["reasoning", "general"], "category": "general"},
    "mixtral": {"strengths": ["reasoning", "general", "coding"], "category": "general"},
    "gemma": {"strengths": ["reasoning", "general"], "category": "general"},
    "gemma2": {"strengths": ["reasoning", "general", "coding"], "category": "general"},
    "phi3": {"strengths": ["reasoning", "coding", "analysis"], "category": "general"},
    "phi4": {"strengths": ["reasoning", "coding", "analysis"], "category": "general"},
    "command-r": {"strengths": ["reasoning", "general", "creative"], "category": "general"},
    "qwen2": {"strengths": ["reasoning", "general", "coding"], "category": "general"},
    "qwen2.5": {"strengths": ["reasoning", "general", "coding", "analysis"], "category": "general"},
    "yi": {"strengths": ["reasoning", "general"], "category": "general"},
    "solar": {"strengths": ["reasoning", "general"], "category": "general"},
    "dolphin": {"strengths": ["general", "creative", "reasoning"], "category": "uncensored"},
    "nous-hermes": {"strengths": ["reasoning", "general"], "category": "general"},
    "wizardlm": {"strengths": ["reasoning", "coding"], "category": "general"},
    "deepseek-r1": {"strengths": ["reasoning", "analysis", "coding"], "category": "reasoning"},
    "qwq": {"strengths": ["reasoning", "analysis"], "category": "reasoning"},
    "llava": {"strengths": ["vision", "general"], "category": "vision"},
    "bakllava": {"strengths": ["vision", "general"], "category": "vision"},
}

# Task type to required strengths mapping
TASK_REQUIREMENTS: dict[str, list[str]] = {
    "coding": ["coding"],
    "reasoning": ["reasoning", "analysis"],
    "creative": ["creative", "general"],
    "analysis": ["analysis", "reasoning"],
    "general": ["general"],
    "vision": ["vision"],
    "research": ["reasoning", "general"],
    "planning": ["reasoning", "analysis"],
    "building": ["coding", "reasoning"],
}

# Keywords for task type detection
TASK_KEYWORDS: dict[str, list[str]] = {
    "coding": [
        "code", "program", "function", "class", "debug", "fix", "implement",
        "script", "compile", "syntax", "algorithm", "api", "endpoint",
        "database", "sql", "python", "javascript", "html", "css", "git",
    ],
    "reasoning": [
        "why", "explain", "reason", "logic", "deduce", "infer", "conclude",
        "analyze", "think", "consider", "evaluate", "compare", "contrast",
    ],
    "creative": [
        "write", "story", "poem", "creative", "imagine", "design",
        "brainstorm", "idea", "concept", "narrative", "compose",
    ],
    "analysis": [
        "analyze", "data", "pattern", "trend", "statistics", "review",
        "examine", "investigate", "research", "study", "report",
    ],
    "vision": [
        "image", "picture", "photo", "see", "look", "visual", "screenshot",
    ],
    "planning": [
        "plan", "strategy", "roadmap", "schedule", "organize", "prioritize",
        "steps", "workflow", "process", "architecture",
    ],
}


def _extract_param_size(model_name: str) -> float:
    """Extract parameter size in billions from model name."""
    match = re.search(r"(\d+\.?\d*)[bB]", model_name)
    if match:
        return float(match.group(1))
    # Check for size indicators in model details
    size_map = {"small": 1, "medium": 7, "large": 13, "xl": 30, "xxl": 70}
    for key, val in size_map.items():
        if key in model_name.lower():
            return val
    return 7.0  # Default assumption


class ModelSelector:
    """Selects the best Ollama model for a given task."""

    def __init__(self) -> None:
        self.available_models: list[dict[str, Any]] = []
        self._model_cache: dict[str, dict[str, Any]] = {}

    def update_models(self, models: list[dict[str, Any]]) -> None:
        """Update the list of available models."""
        self.available_models = models
        self._model_cache.clear()
        for model in models:
            name = model.get("name", "")
            self._model_cache[name] = self._profile_model(name, model)
        logger.info("Updated model list: %d models available", len(models))

    def _profile_model(self, name: str, info: dict[str, Any]) -> dict[str, Any]:
        """Create a capability profile for a model."""
        name_lower = name.lower()
        profile = {
            "name": name,
            "size": info.get("size", 0),
            "param_size": _extract_param_size(name),
            "strengths": ["general"],
            "category": "general",
            "supports_tools": False,
        }

        # Match against known profiles
        for pattern, attrs in MODEL_PROFILES.items():
            if pattern in name_lower:
                profile["strengths"] = attrs["strengths"]
                profile["category"] = attrs["category"]
                break

        # Tool support heuristic - larger models and specific families
        tool_capable = [
            "llama3.1", "llama3.2", "llama3.3", "mistral", "mixtral",
            "qwen2.5", "command-r", "phi3", "phi4", "deepseek-r1",
            "gemma2", "qwen2",
        ]
        for tc in tool_capable:
            if tc in name_lower:
                profile["supports_tools"] = True
                break

        return profile

    def detect_task_type(self, message: str) -> str:
        """Detect the type of task from the user's message."""
        message_lower = message.lower()
        scores: dict[str, int] = {}

        for task_type, keywords in TASK_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in message_lower)
            if score > 0:
                scores[task_type] = score

        if not scores:
            return "general"

        return max(scores, key=scores.get)  # type: ignore[arg-type]

    def select_model(
        self,
        task_type: str = "general",
        prefer_tools: bool = True,
        min_size: float = 0,
        max_size: float = 200,
    ) -> str | None:
        """Select the best model for a given task type."""
        if not self._model_cache:
            logger.warning("No models available for selection")
            return None

        required_strengths = TASK_REQUIREMENTS.get(task_type, ["general"])
        candidates: list[tuple[str, float]] = []

        for name, profile in self._model_cache.items():
            param_size = profile["param_size"]
            if param_size < min_size or param_size > max_size:
                continue

            # Score based on strength overlap
            strength_overlap = len(
                set(profile["strengths"]) & set(required_strengths)
            )
            score = strength_overlap * 10.0

            # Bonus for tool support when needed
            if prefer_tools and profile["supports_tools"]:
                score += 5.0

            # Prefer larger models (more capable) but with diminishing returns
            score += min(param_size / 10.0, 5.0)

            candidates.append((name, score))

        if not candidates:
            # Fall back to first available model
            return next(iter(self._model_cache))

        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = candidates[0][0]
        logger.info(
            "Selected model '%s' for task type '%s' (score: %.1f)",
            selected, task_type, candidates[0][1],
        )
        return selected

    def get_model_info(self, model_name: str) -> dict[str, Any]:
        """Get cached profile info for a model."""
        return self._model_cache.get(model_name, {})

    def list_available(self) -> list[dict[str, Any]]:
        """List all available models with their profiles."""
        return list(self._model_cache.values())
