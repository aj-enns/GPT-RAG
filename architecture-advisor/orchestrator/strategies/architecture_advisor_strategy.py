"""Architecture Advisor strategy.

Wires together the **AI Needs Classifier**, **Architecture Center
retrieval**, and **Recommendation Synthesizer** into a single agent
strategy that plugs into the existing `AgentStrategyFactory` in
`gpt-rag-orchestrator`.

Drop into `gpt-rag-orchestrator/src/strategies/architecture_advisor_strategy.py`,
then:

1. Add `ARCHITECTURE_ADVISOR = "architecture_advisor"` to
   `AgentStrategies` (in `agent_strategies.py`).
2. In `AgentStrategyFactory.get_strategy()` add::

       if strategy_type == AgentStrategies.ARCHITECTURE_ADVISOR:
           return ArchitectureAdvisorStrategy()

3. Set the App Configuration key `AGENT_STRATEGY=architecture_advisor`.

Flow
----
   user description
        │
        ▼
   AINeedsClassifier (separate LLM call, cheap model)
        │
        ├── decision = yes  → retrieve AI patterns
        ├── decision = no   → retrieve non-AI patterns
        └── decision = maybe / low confidence → retrieve BOTH
        │
        ▼
   RecommendationSynthesizer (stronger model)
        │
        ▼
   structured response (primary + alternatives + checklist + next steps)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizableTextQuery

# These imports assume drop-in placement under gpt-rag-orchestrator/src/.
from ..classifier import AINeedsClassifier, AINeedDecision, ClassifierResult
from ..recommender import RecommendationSynthesizer, Recommendation
from .base_agent_strategy import BaseAgentStrategy  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 6
DEFAULT_CONF_THRESHOLD = float(os.environ.get("ARCH_ADVISOR_CLASSIFIER_THRESHOLD", "0.6"))


class ArchitectureAdvisorStrategy(BaseAgentStrategy):
    """Classifier-first architecture advisor strategy."""

    def __init__(
        self,
        classifier: Optional[AINeedsClassifier] = None,
        synthesizer: Optional[RecommendationSynthesizer] = None,
        search_endpoint: Optional[str] = None,
        index_name: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
        confidence_threshold: float = DEFAULT_CONF_THRESHOLD,
    ) -> None:
        super().__init__()
        self._classifier = classifier or AINeedsClassifier()
        self._synthesizer = synthesizer or RecommendationSynthesizer()
        self._search_endpoint = search_endpoint or os.environ[
            "SEARCH_SERVICE_QUERY_ENDPOINT"
        ]
        self._index_name = index_name or os.environ.get(
            "SEARCH_ARCHITECTURE_INDEX_NAME", "architecture"
        )
        self._top_k = top_k
        self._confidence_threshold = confidence_threshold

    # ------------------------------------------------------------ public API

    async def initiate_agent_flow(  # type: ignore[override]
        self,
        conversation_id: str,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """Run classifier → retrieve → synthesize. Returns dict for the UI."""
        logger.info("[arch-advisor] conversation=%s", conversation_id)

        verdict = await self._classifier.classify(user_input)
        logger.info(
            "[arch-advisor] classifier: decision=%s confidence=%.2f",
            verdict.decision.value,
            verdict.confidence,
        )

        candidates = await self._retrieve(user_input, verdict)
        logger.info("[arch-advisor] retrieved %d candidates", len(candidates))

        recommendation = await self._synthesizer.synthesize(
            description=user_input,
            classifier=verdict,
            candidates=candidates,
        )

        return {
            "conversation_id": conversation_id,
            "recommendation": recommendation.to_dict(),
            "rendered_markdown": self._render_markdown(recommendation),
        }

    # --------------------------------------------------------------- retrieve

    async def _retrieve(
        self, user_input: str, verdict: ClassifierResult
    ) -> List[dict]:
        """Hybrid (keyword + vector) search filtered by AI-ness."""

        wants_both = verdict.needs_both_paths(self._confidence_threshold)
        if wants_both:
            filter_clause = None
        elif verdict.decision == AINeedDecision.YES:
            filter_clause = "usesAi eq true"
        else:
            filter_clause = "usesAi eq false"

        # Boost the query with capabilities suggested by the classifier.
        boosted_query = user_input
        if verdict.suggested_capabilities:
            boosted_query = (
                f"{user_input}\n\nCapabilities: "
                + ", ".join(verdict.suggested_capabilities)
            )

        async with SearchClient(
            endpoint=self._search_endpoint,
            index_name=self._index_name,
            credential=DefaultAzureCredential(),
        ) as client:
            results = await client.search(
                search_text=boosted_query,
                vector_queries=[
                    VectorizableTextQuery(
                        text=boosted_query,
                        k_nearest_neighbors=self._top_k * 2,
                        fields="contentVector",
                    )
                ],
                top=self._top_k,
                filter=filter_clause,
                select=[
                    "id",
                    "title",
                    "url",
                    "summary",
                    "azureServices",
                    "usesAi",
                    "costBand",
                    "categories",
                ],
                query_type="semantic",
                semantic_configuration_name="semantic-config",
            )

            candidates: List[dict] = []
            async for item in results:
                candidates.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "summary": item.get("summary", ""),
                        "uses_ai": bool(item.get("usesAi", False)),
                        "azure_services": item.get("azureServices", []) or [],
                        "cost_band": item.get("costBand", "unknown"),
                        "categories": item.get("categories", []) or [],
                        "score": item.get("@search.score", 0.0),
                    }
                )
        return candidates

    # ---------------------------------------------------------------- render

    @staticmethod
    def _render_markdown(rec: Recommendation) -> str:
        lines: List[str] = []
        v = rec.classifier
        lines.append("## Recommendation\n")
        lines.append(
            f"**AI assessment:** `{v.decision.value}` "
            f"(confidence {v.confidence:.0%})  \n"
            f"_{v.rationale}_\n"
        )
        if rec.primary:
            lines.append(f"### Primary pattern — [{rec.primary.title}]({rec.primary.url})")
            lines.append(f"{rec.primary.summary}\n")
            if rec.primary.azure_services:
                lines.append(
                    "**Key services:** " + ", ".join(rec.primary.azure_services) + "\n"
                )
            lines.append(f"**Cost band:** `{rec.primary.cost_band}`\n")
        if rec.why_it_fits:
            lines.append(f"### Why it fits\n{rec.why_it_fits}\n")
        if rec.alternatives:
            lines.append("### Alternatives")
            lines.append("| Pattern | AI? | Cost | Why consider |")
            lines.append("|---------|-----|------|--------------|")
            for alt in rec.alternatives:
                ai = "yes" if alt.uses_ai else "no"
                lines.append(
                    f"| [{alt.title}]({alt.url}) | {ai} | {alt.cost_band} | "
                    f"{alt.summary[:140]}{'…' if len(alt.summary) > 140 else ''} |"
                )
            lines.append("")
        if rec.cost_estimate:
            lines.append(f"### Cost estimate\n{rec.cost_estimate}\n")
        if rec.implementation_checklist:
            lines.append("### Implementation checklist")
            lines.extend(f"- [ ] {step}" for step in rec.implementation_checklist)
            lines.append("")
        if rec.next_steps:
            lines.append("### Next steps")
            lines.extend(f"1. {step}" for step in rec.next_steps)
        return "\n".join(lines)
