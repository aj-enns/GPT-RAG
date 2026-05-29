"""Dataclasses for the AI Needs Classifier.

These are intentionally framework-agnostic so the classifier can be reused
from any strategy (Semantic Kernel agent, Azure AI Foundry agent, plain
FastAPI handler, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class AINeedDecision(str, Enum):
    """Three-way verdict from the classifier.

    `MAYBE` is intentional: many real workloads can be solved either with or
    without AI, and the recommendation flow should surface both.
    """

    YES = "yes"
    NO = "no"
    MAYBE = "maybe"


@dataclass
class ClassifierResult:
    decision: AINeedDecision
    confidence: float  # 0.0 - 1.0
    rationale: str
    ai_signals: List[str] = field(default_factory=list)
    non_ai_signals: List[str] = field(default_factory=list)
    suggested_capabilities: List[str] = field(default_factory=list)
    raw_response: Optional[str] = None

    def needs_both_paths(self, threshold: float) -> bool:
        """When confidence is low, the orchestrator should retrieve both
        AI and non-AI patterns so the synthesizer can present alternatives."""
        return self.decision == AINeedDecision.MAYBE or self.confidence < threshold

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "ai_signals": self.ai_signals,
            "non_ai_signals": self.non_ai_signals,
            "suggested_capabilities": self.suggested_capabilities,
        }
