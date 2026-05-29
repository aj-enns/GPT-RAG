# ADR-001: Classifier-first orchestration for the Architecture Advisor

**Status:** Accepted  
**Date:** 2026-05-28  
**Owners:** GPT-RAG architecture advisor pivot

## Context

We are pivoting the GPT-RAG solution accelerator from a general-purpose
retrieval-augmented chat experience into a focused **Architecture Advisor**.
The advisor helps a customer decide whether their application or workflow
idea genuinely needs AI, or whether an existing Azure architecture pattern
from the [Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/browse/)
already solves the problem. Later phases will plug in a customer-specific
service catalog.

Three design choices needed an explicit decision:

1. Should the "needs AI?" assessment come **before** or **alongside**
   pattern retrieval?
2. Should the classifier be a **separate LLM call** or embedded in the main
   orchestrator prompt?
3. How aggressively should the orchestrator filter retrieval based on the
   classifier verdict?

## Decision

1. **Classifier-first flow.** A dedicated classification step runs before
   any retrieval. Its verdict (`yes` / `no` / `maybe` + confidence)
   determines how the retrieval step filters candidates.
2. **Separate LLM call** for classification, using a smaller and cheaper
   deployment (e.g. `gpt-4o-mini`) than the synthesizer. Output is
   constrained to JSON via `response_format=json_object`.
3. **Confidence-aware filtering.** If the classifier returns `maybe` or
   confidence below `ARCH_ADVISOR_CLASSIFIER_THRESHOLD` (default `0.6`),
   the orchestrator retrieves both AI and non-AI patterns so the
   synthesizer can present alternatives.

## Consequences

### Positive

- The customer always sees a structured "AI assessment + recommendation"
  even when the model is uncertain, instead of a vague chat response.
- Splitting classifier and synthesizer means each step uses the right
  model size, reducing latency and cost.
- The classifier and synthesizer can be evaluated and improved
  independently (each has its own prompt, examples, and test set).
- Retrieval filters on `usesAi` cut search recall noise and produce
  tighter, more decision-ready candidate lists.

### Negative / trade-offs

- Two LLM calls per request (classifier + synthesizer) versus a single
  orchestrated call. Net cost is still typically lower because the
  classifier model is much smaller, but tail latency is slightly worse
  than a single call.
- If the classifier is wrong with high confidence, the wrong filter is
  applied. Mitigations: low-confidence fallback retrieves both sides,
  and the synthesizer prompt is allowed to add an AI alternative even
  when the verdict is "no" if it materially improves the workload.
- Adds a new search index (`architecture-*`) and a new ingestion job to
  the platform footprint. Operational cost is small (one index, weekly
  refresh) but it is real.

### Replaced behavior

- Existing RAG strategies (`single_agent_rag`, `nl2sql`, `mcp`) remain
  available in the orchestrator code and can still be activated via the
  `AGENT_STRATEGY` App Configuration key. The advisor is added as a new
  strategy rather than replacing them — Phase 2 may re-use the RAG
  strategy for follow-up "deep dive" questions on a chosen pattern.

## Alternatives considered

- **Embed classification in the synthesizer prompt.** Simpler but harder
  to test, harder to swap models independently, and forces every query
  through the larger model.
- **Parallel classifier + retrieval.** Slightly lower latency, but the
  retrieval call cannot use the classifier verdict to filter, so we end
  up doing more retrieval work and the synthesizer has to discard
  irrelevant candidates.
- **No classifier at all** (retrieve always, let the synthesizer decide).
  Cheapest but produces noisier retrieval and weaker UX, since the
  customer never gets a clear "does this need AI?" answer.

## Open questions / future work

- Add an evaluation harness (`evaluations/`) that scores the classifier
  against a held-out set of customer-style descriptions.
- Add a "service catalog source" abstraction in the ingester so customer
  catalogs can be plugged in without touching the Learn ingester.
- Add a cost-estimator Semantic Kernel plugin so the synthesizer can
  produce real $ ranges instead of qualitative cost bands.
