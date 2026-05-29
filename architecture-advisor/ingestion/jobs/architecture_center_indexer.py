"""Architecture Center ingester — Phase 1 MVP.

Crawls the Azure Architecture Center "browse" catalog
(https://learn.microsoft.com/en-us/azure/architecture/browse/), extracts
each pattern's title, summary, services, and content, classifies it as
AI-using or not, embeds it, and upserts into Azure AI Search.

Designed to drop into the `Azure/gpt-rag-ingestion` repo under
`jobs/architecture_center_indexer.py` and be invoked on a schedule (Azure
Function timer trigger, Container App job, or `azd deploy` hook).

Phase 1 scope
-------------
* Single-source ingester (Learn / Architecture Center).
* Conservative throttling — Learn is a free resource; be polite.
* Idempotent upserts keyed on the canonical Learn URL.
* Pluggable for Phase 2 (customer service catalog) via the
  `CatalogSource` protocol.

Dependencies (add to gpt-rag-ingestion/requirements.txt)
--------------------------------------------------------
    azure-search-documents>=11.5.0
    azure-identity>=1.17.0
    httpx>=0.27.0
    beautifulsoup4>=4.12.3
    tenacity>=8.2.3
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Protocol
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# --- Tunables ----------------------------------------------------------------

DEFAULT_BROWSE_URL = os.environ.get(
    "LEARN_ARCHITECTURE_BROWSE_URL",
    "https://learn.microsoft.com/en-us/azure/architecture/browse/",
)
USER_AGENT = "gpt-rag-architecture-advisor/0.1 (+https://github.com/Azure/gpt-rag)"
REQUEST_TIMEOUT_SECONDS = 30
MAX_CONCURRENT_FETCHES = 4
REQUEST_DELAY_SECONDS = 0.5  # politeness pause between page fetches

# Heuristic — any of these strings in title/summary/services flags `uses_ai`.
AI_KEYWORDS = {
    "openai",
    "cognitive services",
    "ai foundry",
    "azure ai",
    "machine learning",
    " ml ",
    "form recognizer",
    "document intelligence",
    "vision",
    "speech",
    "language",
    "translator",
    "personalizer",
    "anomaly detector",
    "metrics advisor",
    "bot service",
    "chatbot",
    "copilot",
    "rag",
    "embeddings",
    "vector",
    "llm",
    "generative",
    "predictive",
    "intelligent",
}


# --- Public dataclasses ------------------------------------------------------


@dataclass
class CatalogItem:
    """Normalised pattern from any catalog source."""

    id: str
    title: str
    url: str
    summary: str
    content: str
    azure_services: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    uses_ai: bool = False
    cost_band: str = "unknown"  # low | medium | high | unknown
    source: str = "learn-architecture-center"

    def to_search_doc(self, content_vector: Optional[List[float]] = None) -> dict:
        doc = {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "content": self.content,
            "azureServices": self.azure_services,
            "categories": self.categories,
            "usesAi": self.uses_ai,
            "costBand": self.cost_band,
            "source": self.source,
        }
        if content_vector is not None:
            doc["contentVector"] = content_vector
        return doc


class CatalogSource(Protocol):
    """Protocol every catalog source must implement.

    Phase 2 plug-in: a customer-specific service catalog source can be added
    by implementing this same interface and registering it in the indexer.
    """

    name: str

    async def iter_items(self) -> Iterable[CatalogItem]:  # pragma: no cover
        ...


# --- Learn / Architecture Center source --------------------------------------


class ArchitectureCenterSource:
    """Scrapes the Azure Architecture Center 'browse' catalog."""

    name = "learn-architecture-center"

    def __init__(
        self,
        browse_url: str = DEFAULT_BROWSE_URL,
        max_items: Optional[int] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._browse_url = browse_url
        self._max_items = max_items
        self._client = http_client
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def iter_items(self) -> List[CatalogItem]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        try:
            urls = await self._discover_pattern_urls(client)
            if self._max_items:
                urls = urls[: self._max_items]
            logger.info("Discovered %d architecture pattern URLs", len(urls))

            tasks = [self._fetch_item(client, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if owns_client:
                await client.aclose()

        items: List[CatalogItem] = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                logger.warning("Skipping %s: %s", url, result)
                continue
            if result is not None:
                items.append(result)
        return items

    # ----------------------------------------------------------- discovery

    async def _discover_pattern_urls(self, client: httpx.AsyncClient) -> List[str]:
        """Pull the JSON catalog that powers the browse page.

        The Architecture Center browse page is server-rendered from a JSON
        feed. We try the JSON endpoint first; if Microsoft changes the URL,
        we fall back to parsing the HTML.
        """
        json_endpoint = urljoin(self._browse_url, "azure-architectures-content.json")
        try:
            resp = await client.get(json_endpoint)
            resp.raise_for_status()
            data = resp.json()
            urls = []
            for entry in data.get("results", data if isinstance(data, list) else []):
                href = entry.get("url") or entry.get("href")
                if href:
                    urls.append(self._absolutize(href))
            if urls:
                return sorted(set(urls))
        except Exception as exc:
            logger.info("JSON catalog endpoint not usable (%s); falling back to HTML", exc)

        # HTML fallback — find all anchors pointing to /azure/architecture/.
        resp = await client.get(self._browse_url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            absolute = self._absolutize(href)
            if (
                "/azure/architecture/" in absolute
                and not absolute.endswith("/browse/")
                and absolute != self._browse_url
            ):
                urls.add(absolute.split("#")[0])
        return sorted(urls)

    def _absolutize(self, href: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return urljoin("https://learn.microsoft.com/", href.lstrip("/"))

    # ----------------------------------------------------------- per-page

    async def _fetch_item(
        self, client: httpx.AsyncClient, url: str
    ) -> Optional[CatalogItem]:
        async with self._semaphore:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                retry=retry_if_exception_type(
                    (httpx.HTTPError, httpx.RemoteProtocolError)
                ),
                reraise=True,
            ):
                with attempt:
                    resp = await client.get(url)
                    resp.raise_for_status()
            return self._parse_pattern(url, resp.text)

    def _parse_pattern(self, url: str, html: str) -> Optional[CatalogItem]:
        soup = BeautifulSoup(html, "html.parser")

        title = (soup.title.string if soup.title else "").strip()
        title = re.sub(r"\s*\|\s*Microsoft Learn$", "", title or "")

        # Summary: prefer <meta name="description">, fall back to first <p>.
        summary = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            summary = meta["content"].strip()
        else:
            first_p = soup.find("main")
            if first_p:
                first_p = first_p.find("p")
            if first_p:
                summary = first_p.get_text(" ", strip=True)

        # Main article body — keep this conservative; we strip nav and chrome.
        article = soup.find("main") or soup
        for tag in article.select("nav, header, footer, .breadcrumb, script, style"):
            tag.decompose()
        content = article.get_text(" ", strip=True)
        content = re.sub(r"\s+", " ", content)[:20000]  # cap per pattern

        if not title or not content:
            return None

        services = self._extract_services(soup, content)
        uses_ai = self._classify_ai(title, summary, services, content)

        item_id = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return CatalogItem(
            id=item_id,
            title=title,
            url=url,
            summary=summary or title,
            content=content,
            azure_services=services,
            categories=self._extract_categories(soup),
            uses_ai=uses_ai,
        )

    @staticmethod
    def _extract_services(soup: BeautifulSoup, content: str) -> List[str]:
        services: set[str] = set()
        for tag in soup.select(
            'meta[name="ms.service"], meta[name="ms.subservice"], '
            'meta[name="services"]'
        ):
            value = tag.get("content", "")
            for item in re.split(r"[,;]", value):
                item = item.strip()
                if item:
                    services.add(item)
        # Cheap heuristic on the body for service names like "Azure XYZ".
        for match in re.finditer(r"Azure [A-Z][\w\- ]{2,40}", content):
            services.add(match.group(0).strip(" .,;:"))
        return sorted(services)[:30]

    @staticmethod
    def _extract_categories(soup: BeautifulSoup) -> List[str]:
        categories: set[str] = set()
        for tag in soup.select('meta[name="ms.topic"], meta[name="ms.category"]'):
            value = tag.get("content", "")
            for item in re.split(r"[,;]", value):
                item = item.strip()
                if item:
                    categories.add(item)
        return sorted(categories)

    @staticmethod
    def _classify_ai(
        title: str, summary: str, services: List[str], content: str
    ) -> bool:
        haystack = " ".join(
            [title.lower(), summary.lower(), " ".join(services).lower(), content[:4000].lower()]
        )
        return any(kw in haystack for kw in AI_KEYWORDS)


# --- Indexer -----------------------------------------------------------------


class ArchitectureIndexer:
    """Ingests one or more CatalogSources into Azure AI Search."""

    def __init__(
        self,
        search_endpoint: str,
        index_name: str,
        embedder,  # Callable[[List[str]], Awaitable[List[List[float]]]]
        sources: Optional[List[CatalogSource]] = None,
    ) -> None:
        from azure.identity.aio import DefaultAzureCredential
        from azure.search.documents.aio import SearchClient

        self._search_client = SearchClient(
            endpoint=search_endpoint,
            index_name=index_name,
            credential=DefaultAzureCredential(),
        )
        self._embedder = embedder
        self._sources = sources or [ArchitectureCenterSource()]

    async def run(self) -> dict:
        all_items: List[CatalogItem] = []
        for source in self._sources:
            logger.info("Pulling catalog source: %s", source.name)
            items = await source.iter_items()
            logger.info("  -> %d items from %s", len(items), source.name)
            all_items.extend(items)

        if not all_items:
            return {"indexed": 0, "sources": [s.name for s in self._sources]}

        texts = [
            f"{i.title}\n\n{i.summary}\n\n{i.content[:4000]}" for i in all_items
        ]
        vectors = await self._embedder(texts)

        docs = [
            item.to_search_doc(content_vector=vector)
            for item, vector in zip(all_items, vectors)
        ]

        # Upload in batches of 100 to stay within AI Search limits.
        batch_size = 100
        uploaded = 0
        for start in range(0, len(docs), batch_size):
            batch = docs[start : start + batch_size]
            await self._search_client.merge_or_upload_documents(documents=batch)
            uploaded += len(batch)
            logger.info("  uploaded %d / %d", uploaded, len(docs))

        await self._search_client.close()
        return {
            "indexed": uploaded,
            "sources": [s.name for s in self._sources],
        }


# --- CLI entry point ---------------------------------------------------------


async def _main() -> None:  # pragma: no cover - manual smoke test
    import argparse

    parser = argparse.ArgumentParser(description="Ingest Azure Architecture Center")
    parser.add_argument("--search-endpoint", required=True)
    parser.add_argument("--index-name", required=True)
    parser.add_argument("--max-items", type=int, default=None)
    args = parser.parse_args()

    async def echo_embedder(texts: List[str]) -> List[List[float]]:
        # Replace with the real Azure OpenAI embedder in production.
        return [[0.0] * 1536 for _ in texts]

    indexer = ArchitectureIndexer(
        search_endpoint=args.search_endpoint,
        index_name=args.index_name,
        embedder=echo_embedder,
        sources=[ArchitectureCenterSource(max_items=args.max_items)],
    )
    result = await indexer.run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
