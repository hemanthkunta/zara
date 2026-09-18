"""
ZARA Browser and Web Research Tools:
- WebSearchTool (web_search)
- BrowserOpenTool (browser_open)
- ExtractContentTool (extract_content)
- FollowLinkTool (follow_link)
- CollectSourceTool (collect_source)
- BrowserTool (browser_scrape) [backward compatible]
"""
import urllib.request
import urllib.parse
import re
import json
import datetime
from typing import Dict, Any, List, Optional
from tools.base import BaseTool, ToolResult
from config.settings import RiskLevel
from modules.research import ResearchEngine


class WebSearchTool(BaseTool):
    """Execute web search across authoritative sources returning structured results."""

    def __init__(self, engine: Optional[ResearchEngine] = None):
        super().__init__(
            name="web_search",
            description="Search the web for documentation, articles, or technical answers across authoritative sources.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"}
                },
                "required": ["query"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=25
        )
        self.engine = engine or ResearchEngine()

    def run(self, query: str, max_results: int = 5) -> ToolResult:
        try:
            results = self.engine.search_web(query, max_results=max_results)
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results": results,
                    "count": len(results),
                    "timestamp": datetime.datetime.now().isoformat(),
                    "source_type": "web"
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=f"Web search failed for query '{query}': {str(e)}")


class BrowserOpenTool(BaseTool):
    """Open a web page, sanitize content against prompt injection, and return clean Markdown with links."""

    def __init__(self, engine: Optional[ResearchEngine] = None):
        super().__init__(
            name="browser_open",
            description="Fetch a web page, extract main content into structured Markdown, and isolate untrusted content.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_length": {"type": "integer"}
                },
                "required": ["url"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=20
        )
        self.engine = engine or ResearchEngine()

    def run(self, url: str, max_length: int = 8000) -> ToolResult:
        try:
            data = self.engine.fetch_page(url, timeout=self.timeout_seconds, max_length=max_length)
            if not data.get("success"):
                return ToolResult(success=False, data=data, error=data.get("error", f"Failed to fetch {url}"))
            return ToolResult(success=True, data=data)
        except Exception as e:
            return ToolResult(success=False, data=None, error=f"Failed to open page {url}: {str(e)}")


class ExtractContentTool(BaseTool):
    """Extract targeted evidence and excerpts answering a research question from a webpage."""

    def __init__(self, engine: Optional[ResearchEngine] = None):
        super().__init__(
            name="extract_content",
            description="Extract targeted evidence from an opened webpage answering a specific claim or question.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "target_topic": {"type": "string"},
                    "source_id": {"type": "string"}
                },
                "required": ["url", "target_topic"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=20
        )
        self.engine = engine or ResearchEngine()

    def run(self, url: str, target_topic: str, source_id: str = "source_01") -> ToolResult:
        try:
            page_data = self.engine.fetch_page(url, timeout=self.timeout_seconds)
            if not page_data.get("success"):
                return ToolResult(success=False, data=page_data, error=page_data.get("error", "Fetch failed"))

            evidence_items = self.engine.extract_evidence(page_data, query=target_topic, source_id=source_id)
            return ToolResult(
                success=True,
                data={
                    "url": url,
                    "target_topic": target_topic,
                    "source_id": source_id,
                    "evidence": [ev.to_dict() for ev in evidence_items],
                    "count": len(evidence_items),
                    "timestamp": datetime.datetime.now().isoformat(),
                    "source_type": "web"
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=f"Extract content failed: {str(e)}")


class FollowLinkTool(BaseTool):
    """Navigate by resolving relative or absolute links discovered on a page."""

    def __init__(self, engine: Optional[ResearchEngine] = None):
        super().__init__(
            name="follow_link",
            description="Follow a discovered link from a current page to its destination page.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "base_url": {"type": "string"},
                    "link": {"type": "string"}
                },
                "required": ["base_url", "link"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=20
        )
        self.engine = engine or ResearchEngine()

    def run(self, base_url: str, link: str) -> ToolResult:
        try:
            resolved_url = urllib.parse.urljoin(base_url, link)
            page_data = self.engine.fetch_page(resolved_url, timeout=self.timeout_seconds)
            if not page_data.get("success"):
                return ToolResult(success=False, data=page_data, error=page_data.get("error", "Navigation failed"))
            return ToolResult(
                success=True,
                data={
                    "base_url": base_url,
                    "resolved_url": resolved_url,
                    "title": page_data.get("title"),
                    "domain": page_data.get("domain"),
                    "content": page_data.get("content"),
                    "status_code": page_data.get("status_code"),
                    "timestamp": datetime.datetime.now().isoformat(),
                    "source_type": "web"
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=f"Follow link failed: {str(e)}")


class CollectSourceTool(BaseTool):
    """Register and track an authentic research source with reliability metadata."""

    def __init__(self):
        super().__init__(
            name="collect_source",
            description="Register a verified research source with title, domain, and excerpt into the research evidence ledger.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "relevant_excerpt": {"type": "string"},
                    "reliability": {"type": "string"},
                    "is_authoritative": {"type": "boolean"}
                },
                "required": ["source_id", "url", "title"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=5
        )

    def run(
        self,
        source_id: str,
        url: str,
        title: str,
        relevant_excerpt: str = "",
        reliability: str = "primary",
        is_authoritative: bool = False
    ) -> ToolResult:
        domain = urllib.parse.urlparse(url).netloc or "unknown"
        return ToolResult(
            success=True,
            data={
                "source_id": source_id,
                "url": url,
                "title": title,
                "domain": domain,
                "relevant_excerpt": relevant_excerpt,
                "reliability": reliability,
                "is_authoritative": is_authoritative,
                "retrieved_at": datetime.datetime.now().isoformat(),
                "source_type": "web"
            }
        )


class BrowserTool(BaseTool):
    """Headless scraping and structured HTML-to-Markdown extraction (backward compatible)."""

    def __init__(self, engine: Optional[ResearchEngine] = None):
        super().__init__(
            name="browser_scrape",
            description="Fetch a web page, extract main content as structured Markdown, and discover links.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_length": {"type": "integer"}
                },
                "required": ["url"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=20
        )
        self.engine = engine or ResearchEngine()

    def run(self, url: str, max_length: int = 5000) -> ToolResult:
        try:
            page_data = self.engine.fetch_page(url, timeout=self.timeout_seconds, max_length=max_length)
            if not page_data.get("success"):
                return ToolResult(success=False, data=None, error=page_data.get("error", "Scrape failed"))

            result_data = {
                "url": page_data["url"],
                "status_code": page_data["status_code"],
                "title": page_data["title"],
                "content_type": "text/html",
                "content": page_data["raw_text"][:max_length],
                "discovered_links": page_data["discovered_links"],
                "total_chars": len(page_data["raw_text"]),
                "source_type": "web",
                "timestamp": page_data["timestamp"]
            }
            return ToolResult(success=True, data=result_data)
        except Exception as e:
            return ToolResult(success=False, data=None, error=f"Browser scrape failed for {url}: {str(e)}")
