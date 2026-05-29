"""Synthesizes the final recommendation shown to the customer.

Takes the classifier verdict + retrieved architecture candidates and asks a
stronger LLM to produce a structured response with:

* primary recommended pattern (link + why it fits)
* AI-vs-non-AI alternatives table
* indicative cost range (qualitative if no pricing data is available)
* implementation checklist
* concrete next steps

The output schema is enforced via `response_format=json_object` so the UI
can render it deterministically.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from openai import AsyncAzureOpenAI

from ..classifier.models import ClassifierResult

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
TEMPLATE_PATH = PROMPTS_DIR / "synthesizer_template.txt"


@dataclass
class ArchitectureOption:
    title: str
    url: str
    summary: str
    uses_ai: bool
    azure_services: List[str] = field(default_factory=list)
    cost_band: str = "unknown"  # low | medium | high | unknown


@dataclass
class Recommendation:
    primary: Optional[ArchitectureOption]
    alternatives: List[ArchitectureOption]
    why_it_fits: str
    cost_estimate: str
    implementation_checklist: List[str]
    next_steps: List[str]
    classifier: ClassifierResult

    def to_dict(self) -> dict:
        return {
            "primary": self.primary.__dict__ if self.primary else None,
            "alternatives": [a.__dict__ for a in self.alternatives],
            "why_it_fits": self.why_it_fits,
            "cost_estimate": self.cost_estimate,
            "implementation_checklist": self.implementation_checklist,
            "next_steps": self.next_steps,
            "classifier": self.classifier.to_dict(),
        }


class RecommendationSynthesizer:
    def __init__(
        self,
        azure_endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        deployment: Optional[str] = None,
        api_version: str = "2024-10-21",
        temperature: float = 0.2,
    ) -> None:
        self._endpoint = azure_endpoint or os.environ["AZURE_OPENAI_ENDPOINT"]
        self._deployment = deployment or os.environ.get(
            "ARCH_ADVISOR_SYNTHESIZER_DEPLOYMENT", "gpt-4o"
        )
        self._temperature = temperature

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
                get_bearer_token_provider,
            )

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

        self._template = TEMPLATE_PATH.read_text(encoding="utf-8")

    async def synthesize(
        self,
        description: str,
        classifier: ClassifierResult,
        candidates: List[dict],
    ) -> Recommendation:
        """Build the final structured recommendation.

        `candidates` are raw hits from the architecture AI Search index. Each
        dict is expected to contain at least: title, url, summary,
        uses_ai (bool), azure_services (list), cost_band (str).
        """
        system_prompt = self._template
        user_payload = {
            "customer_description": description,
            "classifier_verdict": classifier.to_dict(),
            "candidates": candidates,
        }

        try:
            response = await self._client.chat.completions.create(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload)},
                ],
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )
        except Exception:
            logger.exception("Synthesizer LLM call failed")
            return self._fallback(classifier, candidates)

        raw = response.choices[0].message.content or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Synthesizer returned non-JSON: %r", raw[:200])
            return self._fallback(classifier, candidates)

        return self._materialise(payload, classifier, candidates)

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _to_option(payload: dict) -> ArchitectureOption:
        return ArchitectureOption(
            title=str(payload.get("title", "")).strip(),
            url=str(payload.get("url", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            uses_ai=bool(payload.get("uses_ai", False)),
            azure_services=list(payload.get("azure_services", []) or []),
            cost_band=str(payload.get("cost_band", "unknown")).lower(),
        )

    def _materialise(
        self,
        payload: dict,
        classifier: ClassifierResult,
        candidates: List[dict],
    ) -> Recommendation:
        primary_raw = payload.get("primary")
        primary = self._to_option(primary_raw) if primary_raw else None
        alternatives = [
            self._to_option(a) for a in (payload.get("alternatives") or [])
        ]
        if not primary and candidates:
            # Last-resort fallback so the UI always has something to render.
            primary = self._to_option(candidates[0])

        return Recommendation(
            primary=primary,
            alternatives=alternatives,
            why_it_fits=str(payload.get("why_it_fits", "")).strip(),
            cost_estimate=str(payload.get("cost_estimate", "Not estimated.")).strip(),
            implementation_checklist=list(
                payload.get("implementation_checklist", []) or []
            ),
            next_steps=list(payload.get("next_steps", []) or []),
            classifier=classifier,
        )

    def _fallback(
        self, classifier: ClassifierResult, candidates: List[dict]
    ) -> Recommendation:
        primary = self._to_option(candidates[0]) if candidates else None
        alternatives = [self._to_option(c) for c in candidates[1:4]]
        return Recommendation(
            primary=primary,
            alternatives=alternatives,
            why_it_fits=(
                "Automatic synthesis failed; showing top retrieval results "
                "directly."
            ),
            cost_estimate="Not estimated.",
            implementation_checklist=[],
            next_steps=[
                "Review the retrieved patterns and re-run with a more specific "
                "description."
            ],
            classifier=classifier,
        )
