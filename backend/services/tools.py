"""Real, best-effort tools used by the chat pipeline.

These perform genuine work against configured backends. When a backend is missing
or unavailable they return an honest status instead of fabricated data.
"""

import json
import logging
import math
import urllib.parse
import xml.etree.ElementTree as ET

import httpx

from backend.config import settings
from backend.db.redis_client import get_redis_client
from backend.services.embeddings import embed

logger = logging.getLogger(__name__)

COLLISION_KEY = "ideator:collision_ideas"
MAX_STORED = 300


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def collision_check(text: str) -> str:
    """Semantic novelty check: compare the idea against previously stored ideas."""
    threshold = settings.COLLISION_SIMILARITY_THRESHOLD
    vector = await embed(text)
    if vector is None:
        return "Collision check skipped — embedding service unavailable."

    try:
        redis = get_redis_client()
        raw = await redis.lrange(COLLISION_KEY, 0, -1)
        best_score = 0.0
        best_text = None
        for item in raw:
            obj = json.loads(item)
            score = _cosine(vector, obj.get("vec", []))
            if score > best_score:
                best_score = score
                best_text = obj.get("text")

        # Persist this idea so future checks can detect self-similarity.
        await redis.lpush(COLLISION_KEY, json.dumps({"text": text, "vec": vector}))
        await redis.ltrim(COLLISION_KEY, 0, MAX_STORED - 1)
        await redis.expire(COLLISION_KEY, 60 * 60 * 24 * 30)
    except Exception as exc:
        logger.warning("Collision check storage failed: %s", exc)
        return "Collision check skipped — memory store unavailable."

    if best_text and best_score >= threshold:
        snippet = best_text if len(best_text) <= 80 else best_text[:77] + "…"
        return (
            f"Heads up — this overlaps with a previously stored idea "
            f"(similarity {best_score:.2f}): \"{snippet}\". Consider what makes yours different."
        )
    return (
        f"No similar claimed idea found (top similarity {best_score:.2f}, "
        f"threshold {threshold:.2f}). This looks novel."
    )


async def web_research(query: str) -> str | None:
    """Search the web via Tavily when a key is configured; otherwise return None.

    Returns a JSON-serialisable string with structured source data so the
    frontend can render individual result cards (title + url + snippet).
    """
    key = settings.TAVILY_API_KEY
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            results = response.json().get("results", [])
    except Exception as exc:
        logger.warning("Web research failed: %s", exc)
        return "Web research unavailable right now."

    if not results:
        return "No relevant sources found."

    # Build a structured payload the frontend can render as cards
    sources = []
    for item in results[:5]:
        title = item.get("title", "")
        url = item.get("url", "")
        snippet = item.get("content", "")[:200] if item.get("content") else ""
        if title or url:
            sources.append({"title": title, "url": url, "snippet": snippet})

    return json.dumps({"type": "web_research", "sources": sources})


async def academic_search(query: str) -> str:
    """Search academic literature via arXiv API (free, open-access, no keys required)."""
    try:
        url = f"https://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(query)}&max_results=5"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            
        root = ET.fromstring(resp.content)
        # Handle XML namespaces
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        
        if not entries:
            return "No relevant academic papers found."
            
        sources = []
        for entry in entries:
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            id_el = entry.find("atom:id", ns)
            
            title = title_el.text.strip() if title_el is not None else "Untitled"
            summary = summary_el.text.strip() if summary_el is not None else ""
            url = id_el.text.strip() if id_el is not None else ""
            
            # Clean up whitespace/newlines
            title = " ".join(title.split())
            snippet = " ".join(summary.split())[:200]
            
            sources.append({
                "title": title,
                "url": url,
                "snippet": snippet
            })
            
        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("Academic search failed: %s", exc)
        return "Academic search service is currently unavailable."


async def github_search(query: str) -> str:
    """Search open-source repositories via GitHub REST API (free, open-access, no keys required)."""
    try:
        url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}&sort=stars&order=desc&per_page=5"
        headers = {
            "User-Agent": "Ideator-App/1.0"
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            
        items = resp.json().get("items", [])
        if not items:
            return "No relevant GitHub repositories found."
            
        sources = []
        for item in items:
            name = item.get("full_name", "GitHub Repo")
            description = item.get("description", "") or ""
            html_url = item.get("html_url", "")
            stars = item.get("stargazers_count", 0)
            language = item.get("language", "")
            
            meta = f"Stars: {stars}"
            if language:
                meta += f" | Language: {language}"
                
            snippet = f"{meta} - {description}"[:200]
            
            sources.append({
                "title": name,
                "url": html_url,
                "snippet": snippet
            })
            
        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("GitHub search failed: %s", exc)
        return "GitHub search service is currently unavailable."


async def fetch_newsletter_feeds(topic: str) -> str:
    """
    Fetch trending newsletters, blog posts, and articles from top departments
    (tech, science, business, or custom topics) using RSS feeds (no API key required).
    """
    topic_clean = topic.strip().lower()
    
    # Select feed URL based on category, defaulting to a custom Google News search feed
    if topic_clean in ["tech", "technology", "engineering"]:
        url = "https://news.ycombinator.com/rss"
    elif topic_clean in ["science", "research"]:
        url = "https://www.sciencedaily.com/rss/top/technology.xml"
    elif topic_clean in ["business", "startups", "finance"]:
        url = "https://techcrunch.com/feed/"
    else:
        # Custom search query via Google News RSS
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}&hl=en-US&gl=US&ceid=US:en"
        
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        
        if not items:
            return f"No recent newsletters or articles found for topic '{topic}'."
            
        sources = []
        for item in items[:5]:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            
            title = title_el.text.strip() if title_el is not None else "Untitled"
            link = link_el.text.strip() if link_el is not None else ""
            
            # Extract clean snippet from description
            snippet = ""
            if desc_el is not None and desc_el.text:
                import re
                clean = re.compile('<.*?>')
                snippet = re.sub(clean, '', desc_el.text).strip()
                snippet = " ".join(snippet.split())[:200]
                
            sources.append({
                "title": title,
                "url": link,
                "snippet": snippet
            })
            
        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("Newsletter feed fetch failed for topic %s: %s", topic, exc)
        return "Newsletter feed service is currently offline."


async def generate_chart(chart_type: str, title: str, labels: list[str] | str, values: list[float] | str, x_label: str = "", y_label: str = "", base_url: str = "http://localhost:8000") -> str:
    """
    Generates a visual chart (bar, line, pie, or scatter) using matplotlib,
    saves the image as a static asset, and returns the absolute markdown image link.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
        import uuid
        import os
        
        # Parse inputs if they were passed as JSON strings or lists
        if isinstance(labels, str):
            try:
                labels = json.loads(labels)
            except Exception:
                labels = [x.strip() for x in labels.split(",") if x.strip()]
                
        if isinstance(values, str):
            try:
                values = json.loads(values)
            except Exception:
                values = [float(x.strip()) for x in values.split(",") if x.strip()]
                
        # Validate inputs
        if not labels or not values or len(labels) != len(values):
            return "Error: labels and values must have the same number of elements and cannot be empty."
            
        fig, ax = plt.subplots(figsize=(8, 5))
        
        # Select chart type
        chart_type_clean = chart_type.strip().lower()
        if chart_type_clean == "bar":
            ax.bar(labels, values, color="#4F46E5") # sleeker indigo color
        elif chart_type_clean == "line":
            ax.plot(labels, values, marker="o", color="#4F46E5", linewidth=2)
        elif chart_type_clean == "pie":
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, colors=plt.cm.Paired.colors)
        elif chart_type_clean == "scatter":
            ax.scatter(labels, values, color="#4F46E5", s=100)
        else:
            ax.bar(labels, values, color="#4F46E5")
            
        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
        if x_label and chart_type_clean != "pie":
            ax.set_xlabel(x_label, fontsize=11, labelpad=10)
        if y_label and chart_type_clean != "pie":
            ax.set_ylabel(y_label, fontsize=11, labelpad=10)
            
        plt.tight_layout()
        
        # Save to static dir
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "charts")
        os.makedirs(static_dir, exist_ok=True)
        
        filename = f"chart_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(static_dir, filename)
        
        plt.savefig(filepath, dpi=150)
        plt.close(fig)
        
        # Generate full URL link
        image_url = f"{base_url}/static/charts/{filename}"
        
        # Return markdown representation so the frontend renders it directly
        return json.dumps({
            "type": "web_research",
            "sources": [
                {
                    "title": f"Generated Chart: {title}",
                    "url": image_url,
                    "snippet": f"Visual {chart_type} chart representing {title}. View absolute link: {image_url}"
                }
            ]
        })
    except Exception as exc:
        logger.warning("Failed to generate chart: %s", exc)
        return "Failed to generate visual chart."
