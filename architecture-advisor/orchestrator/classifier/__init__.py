"""AI Needs Classifier package.

Contains the dedicated LLM-backed classifier that decides whether a
customer-described workflow needs AI, can use a non-AI Azure pattern, or is
ambiguous and needs both options surfaced.
"""

from .ai_needs_classifier import AINeedsClassifier
from .models import ClassifierResult, AINeedDecision

__all__ = ["AINeedsClassifier", "ClassifierResult", "AINeedDecision"]
