"""
ZARA Browser Automation Tool: Headless scraping, structured HTML-to-Markdown extraction, and link discovery.
"""
import urllib.request
import urllib.parse
import re
import json
from typing import Dict, Any, List, Optional
from tools.base import BaseTool, ToolResult
from config.settings import RiskLevel

class BrowserTool(BaseTool):
    def __init__(self):
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
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) ZARA/1.0 Safari/537.36"

    def run(self, url: str, max_length: int = 5000) -> ToolResult:
        try:
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url

            parsed_url = urllib.parse.urlparse(url)
            if not parsed_url.netloc:
                return ToolResult(success=False, data=None, error=f"Invalid URL: {url}")

            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
            )
            # Create resilient SSL context
            import ssl
            try:
                ctx = ssl.create_default_context()
            except Exception:
                ctx = None

            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout_seconds, context=ctx)
            except urllib.error.URLError as ssl_err:
                if "CERTIFICATE_VERIFY_FAILED" in str(ssl_err):
                    unverified_ctx = ssl._create_unverified_context()
                    resp = urllib.request.urlopen(req, timeout=self.timeout_seconds, context=unverified_ctx)
                else:
                    raise

            with resp:
                status_code = resp.status
                content_type = resp.headers.get("Content-Type", "")
                raw_html = resp.read().decode("utf-8", errors="ignore")

            # Extract Title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else parsed_url.netloc

            # Extract Links
            links = []
            for href in re.findall(r'href=["\'](https?://[^"\']+)["\']', raw_html, re.IGNORECASE):
                if href not in links and len(links) < 10:
                    links.append(href)

            # Clean and convert to Markdown
            clean = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
            # Headings
            clean = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", clean, flags=re.IGNORECASE)
            # Paragraphs and breaks
            clean = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"<br\s*/?>", "\n", clean, flags=re.IGNORECASE)
            # Strip remaining tags
            clean = re.sub(r"<[^>]+>", " ", clean)
            # Collapse multiple spaces
            text_lines = [line.strip() for line in clean.splitlines() if line.strip()]
            markdown_content = "\n\n".join(text_lines)

            truncated = markdown_content[:max_length]

            result_data = {
                "url": url,
                "status_code": status_code,
                "title": title,
                "content_type": content_type,
                "content": truncated,
                "discovered_links": links,
                "total_chars": len(markdown_content)
            }

            return ToolResult(success=True, data=result_data)
        except Exception as e:
            return ToolResult(success=False, data=None, error=f"Browser scrape failed for {url}: {str(e)}")
