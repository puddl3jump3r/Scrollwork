"""Web research and scraping capabilities."""

import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class WebResearcher:
    """Web research, search, and scraping capabilities."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=DEFAULT_HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        """Search the web using DuckDuckGo HTML.

        Returns list of {title, url, snippet}.
        """
        session = await self._get_session()
        results: list[dict[str, str]] = []

        try:
            # Use DuckDuckGo HTML version
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error("Search failed with status %d", resp.status)
                    return results
                html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            for result in soup.select(".result"):
                title_el = result.select_one(".result__title a")
                snippet_el = result.select_one(".result__snippet")
                if title_el:
                    href = title_el.get("href", "")
                    # DuckDuckGo wraps URLs in redirects
                    if "uddg=" in str(href):
                        from urllib.parse import parse_qs, urlparse as uparse
                        parsed = uparse(str(href))
                        qs = parse_qs(parsed.query)
                        actual_url = qs.get("uddg", [str(href)])[0]
                    else:
                        actual_url = str(href)

                    results.append({
                        "title": title_el.get_text(strip=True),
                        "url": actual_url,
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    })
                    if len(results) >= max_results:
                        break

        except Exception as e:
            logger.error("Search error: %s", e)

        return results

    async def fetch_page(self, url: str) -> dict[str, Any]:
        """Fetch a web page and return structured content."""
        session = await self._get_session()
        try:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return {"error": f"HTTP {resp.status}", "url": url}

                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    return {
                        "url": url,
                        "content_type": content_type,
                        "text": f"Non-HTML content: {content_type}",
                    }

                html = await resp.text()
                return self._parse_html(html, url)

        except aiohttp.ClientError as e:
            return {"error": str(e), "url": url}

    def _parse_html(self, html: str, url: str) -> dict[str, Any]:
        """Parse HTML and extract structured content."""
        soup = BeautifulSoup(html, "html.parser")

        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Get title
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

        # Get meta description
        meta_desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            meta_desc = meta.get("content", "")

        # Get main content
        main = soup.find("main") or soup.find("article") or soup.find("body")
        text = ""
        if main:
            text = main.get_text(separator="\n", strip=True)
            # Clean up excessive whitespace
            text = re.sub(r"\n{3,}", "\n\n", text)

        # Extract links
        links: list[dict[str, str]] = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if href and not href.startswith(("#", "javascript:")):
                absolute = urljoin(url, href)
                links.append({
                    "text": a.get_text(strip=True),
                    "url": absolute,
                })

        # Truncate very long text
        if len(text) > 15000:
            text = text[:15000] + "\n\n[Content truncated...]"

        return {
            "url": url,
            "title": title,
            "description": meta_desc,
            "text": text,
            "links": links[:50],  # Limit links
        }

    async def scrape_text(self, url: str) -> str:
        """Simple text extraction from a URL."""
        result = await self.fetch_page(url)
        if "error" in result:
            return f"Error fetching {url}: {result['error']}"
        return result.get("text", "No content found")

    async def fetch_json(self, url: str) -> dict[str, Any]:
        """Fetch a JSON API endpoint."""
        session = await self._get_session()
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}
