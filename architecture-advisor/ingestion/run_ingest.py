"""One-shot runner for the Architecture Center ingester.

Usage (from repo root, with the project venv active):

    python architecture-advisor/ingestion/run_ingest.py `
        --search-endpoint https://srch-<token>.search.windows.net `
        --index-name architecture-<token> `
        --aoai-endpoint https://aif-<token>.cognitiveservices.azure.com/ `
        --embedding-deployment text-embedding `
        [--max-items 20]

Auth: DefaultAzureCredential (uses `az login`). Caller needs
`Search Index Data Contributor` on the search service and
`Cognitive Services OpenAI User` on the AI Foundry account.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import List

# Load the indexer module directly by path — `jobs/__init__.py` in the
# sibling repo eagerly imports the full ingestion stack (App Config,
# blob, etc.) which we don't want for this one-shot run.
import importlib.util  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEXER_PATH = (
    REPO_ROOT.parent / "gpt-rag-ingestion" / "jobs" / "architecture_center_indexer.py"
)
_spec = importlib.util.spec_from_file_location(
    "architecture_center_indexer", INDEXER_PATH,
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["architecture_center_indexer"] = _mod
_spec.loader.exec_module(_mod)
ArchitectureCenterSource = _mod.ArchitectureCenterSource
ArchitectureIndexer = _mod.ArchitectureIndexer

from azure.identity import DefaultAzureCredential, get_bearer_token_provider  # noqa: E402
from openai import AsyncAzureOpenAI  # noqa: E402


def build_embedder(endpoint: str, deployment: str, api_version: str):
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    client = AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        api_version=api_version,
        azure_ad_token_provider=token_provider,
    )

    async def embed(texts: List[str]) -> List[List[float]]:
        from openai import RateLimitError, APIError
        vectors: List[List[float]] = []
        batch = 4
        for start in range(0, len(texts), batch):
            chunk = texts[start : start + batch]
            delay = 15.0
            for attempt in range(10):
                try:
                    resp = await client.embeddings.create(model=deployment, input=chunk)
                    vectors.extend(d.embedding for d in resp.data)
                    logging.info("embedded %d / %d", len(vectors), len(texts))
                    break
                except RateLimitError as e:
                    wait = getattr(e, "retry_after", None) or delay
                    logging.warning("429 rate limit; sleeping %ss (attempt %d)", wait, attempt + 1)
                    await asyncio.sleep(wait)
                    delay = min(delay * 1.5, 60)
                except APIError as e:
                    logging.warning("APIError %s; retrying in %ss", e, delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 1.5, 60)
            else:
                raise RuntimeError(f"embeddings failed after retries for batch starting {start}")
            await asyncio.sleep(2.0)
        return vectors

    return embed


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search-endpoint", required=True)
    parser.add_argument("--index-name", required=True)
    parser.add_argument("--aoai-endpoint", required=True)
    parser.add_argument("--embedding-deployment", required=True)
    parser.add_argument("--api-version", default="2024-10-21")
    parser.add_argument("--max-items", type=int, default=None,
                        help="Limit pages fetched (smoke test).")
    args = parser.parse_args()

    embedder = build_embedder(
        args.aoai_endpoint, args.embedding_deployment, args.api_version,
    )
    indexer = ArchitectureIndexer(
        search_endpoint=args.search_endpoint,
        index_name=args.index_name,
        embedder=embedder,
        sources=[ArchitectureCenterSource(max_items=args.max_items)],
    )
    result = await indexer.run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
