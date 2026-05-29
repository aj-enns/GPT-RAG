"""AI Needs Classifier — a dedicated LLM call that decides if a described
workflow needs AI.

Design notes
------------
* Runs as a **separate LLM call** with its own (cheaper) deployment so the
  decision step stays fast and inexpensive even when the synthesizer uses a
  larger model.
* Uses **structured JSON output** (response_format=json_object) so the
  caller never has to parse free-form prose.
* Ships with **few-shot examples** loaded from
  `prompts/classifier_examples.jsonl` to anchor the model's behavior.
* Treats deserialization failures as a `MAYBE` (with low confidence) so the
  pipeline always returns a usable result and the orchestrator can fall back
  to retrieving both AI and non-AI candidates.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional

from openai import AsyncAzureOpenAI

from .models import AINeedDecision, ClassifierResult

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "classifier_system.txt"
EXAMPLES_PATH = PROMPTS_DIR / "classifier_examples.jsonl"


class AINeedsClassifier:
    """Wraps a single Azure OpenAI call dedicated to AI-need classification."""

    def __init__(
        self,
        azure_endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        deployment: Optional[str] = None,
        api_version: str = "2024-10-21",
        temperature: float = 0.0,
        max_examples: int = 6,
    ) -> None:
        self._endpoint = azure_endpoint or os.environ["AZURE_OPENAI_ENDPOINT"]
        self._deployment = deployment or os.environ.get(
            "ARCH_ADVISOR_CLASSIFIER_DEPLOYMENT", "gpt-4o-mini"
        )
        self._temperature = temperature
        self._max_examples = max_examples

        # Auth: prefer Entra (managed identity / az login) over API key.
        if api_key:
            self._client = AsyncAzureOpenAI(
                azure_endpoint=self._endpoint,
                api_key=api_key,
                api_version=api_version,
            )
        else:
            from azure.identity.aio import (
                ChainedTokenCredential,
                DefaultAzureCredential,
                ManagedIdentityCredential,
            )
            from azure.identity.aio import get_bearer_token_provider

            credential = ChainedTokenCredential(
                ManagedIdentityCredential(),
                DefaultAzureCredential(),
            )
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            self._client = AsyncAzureOpenAI(
                azure_endpoint=self._endpoint,
                azure_ad_token_provider=token_provider,
                api_version=api_version,
            )

        self._system_prompt = self._load_system_prompt()
        self._examples = list(self._load_examples())

    # ---------------------------------------------------------------- prompts

    @staticmethod
    def _load_system_prompt() -> str:
        if not SYSTEM_PROMPT_PATH.exists():
            raise FileNotFoundError(
                f"classifier_system.txt not found at {SYSTEM_PROMPT_PATH}"
            )
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    @staticmethod
    def _load_examples() -> Iterable[dict]:
        if not EXAMPLES_PATH.exists():
            logger.warning("classifier_examples.jsonl missing — zero-shot mode")
            return
        with EXAMPLES_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping bad example line: %s", exc)

    # ------------------------------------------------------------------- main

    async def classify(self, description: str) -> ClassifierResult:
        """Return a structured verdict for the given workflow description."""
        if not description or not description.strip():
            return ClassifierResult(
                decision=AINeedDecision.MAYBE,
                confidence=0.0,
                rationale="Empty description — defer to retrieval.",
            )

        messages: List[dict] = [{"role": "system", "content": self._system_prompt}]
        for example in self._examples[: self._max_examples]:
            messages.append({"role": "user", "content": example["input"]})
            messages.append(
                {"role": "assistant", "content": json.dumps(example["output"])}
            )
        messages.append({"role": "user", "content": description.strip()})

        try:
            response = await self._client.chat.completions.create(
                model=self._deployment,
                messages=messages,
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )
        except Exception:
            logger.exception("Classifier LLM call failed")
            return ClassifierResult(
                decision=AINeedDecision.MAYBE,
                confidence=0.0,
                rationale="Classifier call failed — defer to retrieval.",
            )

        raw = response.choices[0].message.content or "{}"
        return self._parse(raw)

    # ------------------------------------------------------------------ parse

    @staticmethod
    def _parse(raw: str) -> ClassifierResult:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Classifier returned non-JSON output: %r", raw[:200])
            return ClassifierResult(
                decision=AINeedDecision.MAYBE,
                confidence=0.0,
                rationale="Could not parse classifier output.",
                raw_response=raw,
            )

        decision_raw = str(payload.get("decision", "maybe")).lower()
        try:
            decision = AINeedDecision(decision_raw)
        except ValueError:
            decision = AINeedDecision.MAYBE

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(confidence, 1.0))

        return ClassifierResult(
            decision=decision,
            confidence=confidence,
            rationale=str(payload.get("rationale", "")).strip(),
            ai_signals=list(payload.get("ai_signals", []) or []),
            non_ai_signals=list(payload.get("non_ai_signals", []) or []),
            suggested_capabilities=list(payload.get("suggested_capabilities", []) or []),
            raw_response=raw,
        )
