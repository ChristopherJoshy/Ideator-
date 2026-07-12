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
from backend.db.qdrant_client import get_qdrant_client
from qdrant_client.http import models
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

    best_score = 0.0
    best_text = None
    qdrant_worked = False

    # 1. Try Qdrant (which performs native server-side vector similarity search)
    try:
        qdrant = get_qdrant_client()
        search_result = await qdrant.query_points(
            collection_name="claimed_idea_vectors",
            query=vector,
            limit=1
        )
        if search_result.points:
            closest_point = search_result.points[0]
            best_score = closest_point.score
            best_text = closest_point.payload.get("text")
            
        # Save to Qdrant
        import uuid
        await qdrant.upsert(
            collection_name="claimed_idea_vectors",
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={"text": text}
                )
            ]
        )
        qdrant_worked = True
    except Exception as qdrant_exc:
        logger.warning("Collision check Qdrant querying failed: %s. Trying Redis fallback...", qdrant_exc)

    # 2. Redis Fallback (only run if Qdrant failed)
    if not qdrant_worked:
        try:
            redis = get_redis_client()
            raw = await redis.lrange(COLLISION_KEY, 0, -1)
            for item in raw:
                obj = json.loads(item)
                score = _cosine(vector, obj.get("vec", []))
                if score > best_score:
                    best_score = score
                    best_text = obj.get("text")

            # Persist to Redis
            await redis.lpush(COLLISION_KEY, json.dumps({"text": text, "vec": vector}))
            await redis.ltrim(COLLISION_KEY, 0, MAX_STORED - 1)
            await redis.expire(COLLISION_KEY, 60 * 60 * 24 * 30)
        except Exception as redis_exc:
            logger.warning("Collision check Redis fallback failed: %s", redis_exc)
            if not best_text:
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
    """Search the web via Tavily when a key is configured; falls back to DuckDuckGo (ddgs).

    Returns a JSON-serialisable string with structured source data so the
    frontend can render individual result cards (title + url + snippet).
    """
    key = settings.TAVILY_API_KEY
    if key:
        # --- Tavily primary path ---
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
            logger.warning("Tavily web research failed: %s", exc)
            results = []

        if results:
            sources = []
            for item in results[:5]:
                title = item.get("title", "")
                url = item.get("url", "")
                snippet = item.get("content", "")[:200] if item.get("content") else ""
                if title or url:
                    sources.append({"title": title, "url": url, "snippet": snippet})
            if sources:
                return json.dumps({"type": "web_research", "sources": sources})

    # --- DuckDuckGo fallback (zero key, ddgs library) ---
    try:
        from ddgs import DDGS
        results_ddg = list(DDGS().text(query, max_results=5))
        if not results_ddg:
            return "No relevant sources found."
        sources = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": (r.get("body", "") or "")[:200],
            }
            for r in results_ddg
            if r.get("title") or r.get("href")
        ]
        if sources:
            return json.dumps({"type": "web_research", "sources": sources})
        return "No relevant sources found."
    except Exception as exc:
        logger.warning("DuckDuckGo fallback failed: %s", exc)
        return "Web research unavailable right now."


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


async def hacker_news_search(query: str) -> str:
    """Search Hacker News via Algolia API (free, no key, 10k req/hr).

    Returns the top stories + discussions related to a query — essential
    for gauging developer/startup community sentiment on any topic.
    """
    try:
        url = f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(query)}&tags=story&hitsPerPage=6"
        headers = {"User-Agent": "Ideator-App/1.0"}
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        hits = resp.json().get("hits", [])
        if not hits:
            return "No relevant Hacker News stories found."

        sources = []
        for hit in hits:
            title = hit.get("title", "Untitled")
            story_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            points = hit.get("points") or 0
            num_comments = hit.get("num_comments") or 0
            author = hit.get("author", "")
            snippet = f"▲ {points} pts · {num_comments} comments · by {author}"
            sources.append({"title": title, "url": story_url, "snippet": snippet})

        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("Hacker News search failed: %s", exc)
        return "Hacker News search is currently unavailable."


async def wikipedia_summary(topic: str) -> str:
    """Fetch a concise Wikipedia summary for a topic (free, no key, Wikimedia REST API).

    Perfect for instantly grounding conversations in factual, encyclopaedic context
    about a technology, domain, concept, or person.
    """
    try:
        # First, search for the best matching article
        search_url = (
            f"https://en.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={urllib.parse.quote(topic)}&format=json&srlimit=1"
        )
        headers = {"User-Agent": "Ideator-App/1.0 (educational/research tool)"}
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            search_resp = await client.get(search_url, headers=headers)
            search_resp.raise_for_status()
            search_data = search_resp.json()

        results = search_data.get("query", {}).get("search", [])
        if not results:
            return f"No Wikipedia article found for '{topic}'."

        page_title = results[0]["title"]
        encoded_title = urllib.parse.quote(page_title.replace(" ", "_"))

        # Fetch the summary for the matched article
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            summary_resp = await client.get(summary_url, headers=headers)
            summary_resp.raise_for_status()
            data = summary_resp.json()

        extract = data.get("extract", "")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
        description = data.get("description", "")

        if not extract:
            return f"No summary available for '{topic}' on Wikipedia."

        snippet = extract[:300] + ("…" if len(extract) > 300 else "")
        title_display = f"{page_title}" + (f" — {description}" if description else "")

        sources = [{"title": title_display, "url": page_url, "snippet": snippet}]
        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("Wikipedia summary failed for topic '%s': %s", topic, exc)
        return "Wikipedia lookup is currently unavailable."


async def reddit_search(query: str) -> str:
    """Search Reddit posts using search engines (Tavily or DuckDuckGo) scoped to reddit.com.

    Returns top discussions — ideal for validating whether a pain point is widely felt.
    """
    import re
    scoped_query = f"site:reddit.com {query}"
    key = settings.TAVILY_API_KEY
    results = []
    
    # 1. Try Tavily first if key is available
    if key:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": key,
                        "query": scoped_query,
                        "max_results": 5,
                        "search_depth": "basic",
                        "include_answer": False,
                    },
                )
                response.raise_for_status()
                results = response.json().get("results", [])
        except Exception as exc:
            logger.warning("Tavily search failed for Reddit query: %s", exc)
            results = []

    # 2. Try DuckDuckGo fallback if Tavily yielded no results
    if not results:
        try:
            from ddgs import DDGS
            results_ddg = list(DDGS().text(scoped_query, max_results=5))
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "content": r.get("body", ""),
                }
                for r in results_ddg
                if r.get("title") or r.get("href")
            ]
        except Exception as exc:
            logger.warning("DuckDuckGo fallback failed for Reddit query: %s", exc)

    if not results:
        return "No relevant Reddit posts found."

    sources = []
    for item in results[:5]:
        title = item.get("title", "")
        # Clean title
        title = title.replace(" - Reddit", "").replace(" : r/reddit", "").replace(" : Reddit", "").strip()
        url = item.get("url", "")
        snippet = item.get("content", "")[:200] if item.get("content") else ""
        
        # Try to parse subreddit name from url
        subreddit = "reddit"
        match = re.search(r"reddit\.com/r/([^/]+)", url)
        if match:
            subreddit = f"r/{match.group(1)}"
            
        snippet_text = f"{subreddit}"
        if snippet:
            snippet_text += f" — {snippet}"
            
        sources.append({"title": title, "url": url, "snippet": snippet_text})

    return json.dumps({"type": "web_research", "sources": sources})


async def npm_search(query: str) -> str:
    """Search the npm registry for JavaScript packages (free, no key, no rate limit).

    Useful for discovering existing JS/TS libraries, tools, and frameworks that
    relate to an idea — helping avoid reinventing the wheel.
    """
    try:
        url = f"https://registry.npmjs.org/-/v1/search?text={urllib.parse.quote(query)}&size=5"
        headers = {"User-Agent": "Ideator-App/1.0"}
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        objects = resp.json().get("objects", [])
        if not objects:
            return "No relevant npm packages found."

        sources = []
        for obj in objects:
            pkg = obj.get("package", {})
            name = pkg.get("name", "Unnamed")
            description = pkg.get("description", "") or ""
            version = pkg.get("version", "")
            npm_url = f"https://www.npmjs.com/package/{name}"
            downloads = obj.get("score", {}).get("detail", {}).get("popularity", 0)
            keyword_list = pkg.get("keywords", []) or []
            keywords = ", ".join(keyword_list[:4])

            snippet = f"v{version}"
            if keywords:
                snippet += f" · {keywords}"
            if description:
                snippet += f" — {description[:120]}"

            sources.append({"title": f"npm: {name}", "url": npm_url, "snippet": snippet})

        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("npm search failed: %s", exc)
        return "npm registry search is currently unavailable."


async def crossref_search(query: str) -> str:
    """Search CrossRef for DOI-verified academic papers across all disciplines (free, no key).

    Unlike arXiv (CS/Physics focused), CrossRef covers all fields: medicine,
    economics, social science, engineering, etc. — with DOI links and citation counts.
    """
    try:
        params = urllib.parse.urlencode({
            "query": query,
            "rows": 5,
            "select": "title,author,published,DOI,abstract,is-referenced-by-count,container-title",
            "mailto": "ideator@example.com",  # "polite pool" = higher rate limits
        })
        url = f"https://api.crossref.org/works?{params}"
        headers = {"User-Agent": "Ideator-App/1.0 (mailto:ideator@example.com)"}
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        items = resp.json().get("message", {}).get("items", [])
        if not items:
            return "No relevant papers found via CrossRef."

        sources = []
        for item in items:
            raw_title = item.get("title", [])
            title = raw_title[0] if raw_title else "Untitled"
            doi = item.get("DOI", "")
            doi_url = f"https://doi.org/{doi}" if doi else ""
            journal_list = item.get("container-title", [])
            journal = journal_list[0] if journal_list else ""
            pub_date = item.get("published", {}).get("date-parts", [[None]])[0]
            year = pub_date[0] if pub_date else ""
            citations = item.get("is-referenced-by-count", 0)
            abstract_raw = item.get("abstract", "") or ""
            # CrossRef abstracts can contain JATS XML — strip tags
            import re
            abstract_clean = re.sub(r"<[^>]+>", "", abstract_raw).strip()
            snippet = f"Cited {citations}× · {journal} ({year})"
            if abstract_clean:
                snippet += f" — {abstract_clean[:150]}"

            sources.append({"title": title, "url": doi_url, "snippet": snippet})

        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("CrossRef search failed: %s", exc)
        return "CrossRef search is currently unavailable."


async def world_bank_indicator(query: str) -> str:
    """Fetch World Bank economic data for market sizing and economic context (free, no key).

    Automatically resolves natural-language queries into World Bank indicator series
    (e.g., 'GDP India', 'inflation USA', 'internet usage Nigeria').
    """
    # Mapping common query keywords to World Bank indicator codes
    INDICATOR_MAP = {
        "gdp": "NY.GDP.MKTP.CD",
        "population": "SP.POP.TOTL",
        "inflation": "FP.CPI.TOTL.ZG",
        "unemployment": "SL.UEM.TOTL.ZS",
        "internet": "IT.NET.USER.ZS",
        "mobile": "IT.CEL.SETS.P2",
        "poverty": "SI.POV.DDAY",
        "electricity": "EG.ELC.ACCS.ZS",
        "co2": "EN.ATM.CO2E.PC",
        "education": "SE.ADT.LITR.ZS",
        "health": "SH.XPD.CHEX.GD.ZS",
        "trade": "NE.TRD.GNFS.ZS",
    }

    # Country code guessing (common countries)
    COUNTRY_MAP = {
        "india": "IN", "china": "CN", "usa": "US", "united states": "US",
        "uk": "GB", "united kingdom": "GB", "germany": "DE", "france": "FR",
        "japan": "JP", "brazil": "BR", "nigeria": "NG", "kenya": "KE",
        "indonesia": "ID", "pakistan": "PK", "bangladesh": "BD", "mexico": "MX",
        "russia": "RU", "south africa": "ZA", "australia": "AU", "canada": "CA",
        "world": "WLD", "global": "WLD",
    }

    query_lower = query.lower()
    indicator_code = next(
        (code for keyword, code in INDICATOR_MAP.items() if keyword in query_lower),
        "NY.GDP.MKTP.CD"  # Default to GDP
    )
    country_code = next(
        (code for name, code in COUNTRY_MAP.items() if name in query_lower),
        "WLD"  # Default to world
    )

    try:
        url = (
            f"https://api.worldbank.org/v2/country/{country_code}/indicator/{indicator_code}"
            f"?format=json&mrv=5&per_page=5"
        )
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        data_list = resp.json()
        if not isinstance(data_list, list) or len(data_list) < 2:
            return "No World Bank data found for this query."

        records = [r for r in data_list[1] if r.get("value") is not None]
        if not records:
            return "No recent World Bank data available for this indicator."

        indicator_name = records[0].get("indicator", {}).get("value", indicator_code)
        country_name = records[0].get("country", {}).get("value", country_code)
        wb_url = f"https://data.worldbank.org/indicator/{indicator_code}?locations={country_code}"

        snippet_parts = [f"{r['date']}: {r['value']:,.1f}" for r in records[:5]]
        snippet = " | ".join(snippet_parts)

        sources = [{
            "title": f"World Bank: {indicator_name} — {country_name}",
            "url": wb_url,
            "snippet": snippet
        }]
        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("World Bank indicator fetch failed: %s", exc)
        return "World Bank data is currently unavailable."


async def coinpaprika(query: str) -> str:
    """Fetch cryptocurrency data from Coinpaprika (free, no key, 10 req/sec).

    Returns price, market cap, description, and social links for a coin.
    Useful for Web3/crypto ideation and market context.
    """
    try:
        # First, search for coin by name/symbol
        headers = {"User-Agent": "Ideator-App/1.0"}
        coins_url = "https://api.coinpaprika.com/v1/coins"
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            coins_resp = await client.get(coins_url, headers=headers)
            coins_resp.raise_for_status()
            all_coins = coins_resp.json()

        query_lower = query.lower().strip()
        # Find best matching coin
        matched = next(
            (c for c in all_coins if c.get("symbol", "").lower() == query_lower
             or c.get("name", "").lower() == query_lower),
            None
        )
        # Fallback: partial name match
        if not matched:
            matched = next(
                (c for c in all_coins if query_lower in c.get("name", "").lower()
                 or query_lower in c.get("symbol", "").lower()),
                None
            )

        if not matched:
            return f"No cryptocurrency matching '{query}' found on Coinpaprika."

        coin_id = matched["id"]
        # Fetch ticker (price data) and coin details in parallel
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            ticker_resp = await client.get(
                f"https://api.coinpaprika.com/v1/tickers/{coin_id}", headers=headers
            )
            ticker_resp.raise_for_status()
            ticker = ticker_resp.json()

        quotes = ticker.get("quotes", {}).get("USD", {})
        price = quotes.get("price", 0)
        market_cap = quotes.get("market_cap", 0)
        change_24h = quotes.get("percent_change_24h", 0)
        change_7d = quotes.get("percent_change_7d", 0)

        name = ticker.get("name", query)
        symbol = ticker.get("symbol", "")
        rank = ticker.get("rank", "?")

        snippet = (
            f"Rank #{rank} · ${price:,.4f} USD · "
            f"MCap: ${market_cap:,.0f} · "
            f"24h: {change_24h:+.1f}% · 7d: {change_7d:+.1f}%"
        )
        coin_url = f"https://coinpaprika.com/coin/{coin_id}/"

        sources = [{"title": f"{name} ({symbol}) — Coinpaprika", "url": coin_url, "snippet": snippet}]
        return json.dumps({"type": "web_research", "sources": sources})
    except Exception as exc:
        logger.warning("Coinpaprika fetch failed: %s", exc)
        return "Cryptocurrency data is currently unavailable."


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
    """Fetch trending newsletters, blog posts, and articles from top departments
    (tech, science, business, AI, VC, or custom topics) using RSS feeds (no API key required).
    """
    topic_clean = topic.strip().lower()

    # Extended feed map with high-signal sources
    FEED_MAP = {
        ("tech", "technology", "engineering"): "https://news.ycombinator.com/rss",
        ("ai", "artificial intelligence", "machine learning", "llm"): "https://aiweekly.co/issues.rss",
        ("science", "research"): "https://www.sciencedaily.com/rss/top/technology.xml",
        ("business", "startups", "finance"): "https://techcrunch.com/startups/feed/",
        ("vc", "venture capital", "investment"): "https://a16z.com/feed/",
        ("product", "launch", "producthunt"): "https://www.producthunt.com/feed",
        ("trends", "trending", "viral"): "https://explodingtopics.com/blog/feed",
    }

    url = None
    for keys, feed_url in FEED_MAP.items():
        if any(k in topic_clean for k in keys):
            url = feed_url
            break

    if not url:
        # Google News RSS fallback for custom topics
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
    """Generates a visual chart (bar, line, pie, or scatter) using matplotlib,
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
