import asyncio
import re
import time
import httpx
from xml.etree import ElementTree

# Common US-listed tickers + crypto symbols we scan headlines for.
# Tickers we scan headlines for. NOTE: matching is case-sensitive on uppercase
# tokens only, so common words (now, net, car, flow, ai, c, u) never false-match.
TICKER_PATTERNS = re.compile(
    r"\b(AAPL|MSFT|NVDA|TSLA|AMZN|META|GOOGL|GOOG|NFLX|AMD|INTC|AVGO|ORCL|ADBE|CRM|CSCO|"
    r"QCOM|MU|PLTR|SNOW|UBER|SHOP|BA|XOM|CVX|CAT|GE|F|GM|JPM|GS|MS|BAC|WFC|C|DIS|NKE|"
    r"SBUX|MCD|WMT|PG|KO|PEP|JNJ|PFE|MRK|UNH|LLY|ABBV|DOW|APP|AFRM|COIN|HOOD|SOFI|RIVN|"
    r"LCID|TWLO|NET|DDOG|MDB|ZS|OKTA|DOCU|ZM|TEAM|WDAY|NOW|SNOW|PANW|CRWD|FTNT|MRVL|"
    r"TXN|ADI|NXPI|STX|WDC|SMCI|DELL|HPQ|HPE|IBM|T|VZ|TMUS|ATVI|EA|TTWO|UBER|LYFT|ABNB|"
    r"BKNG|EXPE|MAR|HLT|CCL|RCL|NCLH|DAL|UAL|AAL|LUV|JBLU|ALK|CAR|HTZ|XPEV|NIO|LI|BYDDY|"
    r"JD|BABA|PDD|BIDU|TCEHY|SE|GRAB|SHOP|ETSY|EBAY|MELI|SEA|DOCS|PATH|U|RBLX|C3|AI|"
    r"BTC|ETH|SOL|XRP|DOGE|BNB|ADA|DOT|AVAX|LINK|MATIC|LTC|UNI|SHIB|XMR|ETC|APT|ARB|OP|"
    r"SUI|SEI|INJ|TIA|PEPE|WIF|BONK|ORDI|RUNE|STX|HBAR|ALGO|NEAR|FIL|ATOM|XTZ|EGLD|FTM|"
    r"GALA|IMX|SAND|MANA|AXS|ENJ|CHZ|FLOW|ICP|MINA|ZEC|DASH|KSM|DOT|GLM)\b",
)
# Uppercase-only noise tokens that are valid tickers but too common as words.
_TICKER_NOISE = {"C", "U", "AI", "MS", "OP", "SE", "F", "GE", "LI", "T", "BA"}


def extract_tickers(title: str) -> list[str]:
    """Tickers mentioned in a headline - only matches real uppercase ticker tokens."""
    if not title:
        return []
    found = TICKER_PATTERNS.findall(title)
    return sorted({t for t in found if t not in _TICKER_NOISE})

_cache = {}
_cache_ttl = {}

NEWS_FEEDS = {
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
    "Reuters Markets": "https://feeds.reuters.com/reuters/marketsNews",
    "Reuters Tech": "https://feeds.reuters.com/reuters/technologyNews",
    "CNBC Top": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "CNBC Markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "CNBC Finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "MarketWatch Top": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "MarketWatch Markets": "https://feeds.marketwatch.com/marketwatch/marketpulse/",
    "Investing.com": "https://www.investing.com/rss/news_285.rss",
    "Bloomberg via Google": "https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
    "Seeking Alpha": "https://seekingalpha.com/market_currents.xml",
    "Financial Times": "https://www.ft.com/rss/home",
    "WSJ Markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "Barrons": "https://www.barrons.com/feed",
    "TheStreet": "https://www.thestreet.com/feeds/all.rss",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "DeFi Pulse": "https://defipulse.com/blog/feed",
}


MEDIA_NS = "{http://search.yahoo.com/mrss/}"


def _extract_image(item) -> str:
    """Best-effort thumbnail from enclosure, media:content/thumbnail, or description img."""
    for enc in item.findall("enclosure"):
        if (enc.get("type") or "").startswith("image"):
            return enc.get("url", "")
    for tag in (f"{MEDIA_NS}content", f"{MEDIA_NS}thumbnail"):
        node = item.find(tag)
        if node is not None and node.get("url"):
            return node.get("url", "")
    desc = item.findtext("description", "")
    if desc:
        import re

        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc)
        if m:
            return m.group(1)
    return ""


def _parse_rss(xml_text: str, source: str) -> list[dict]:
    articles = []
    try:
        root = ElementTree.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            if title:
                articles.append(
                    {
                        "source": source,
                        "title": title.strip(),
                        "url": link.strip() if link else "",
                        "published": pub_date.strip() if pub_date else "",
                        "summary": description.strip()[:200] if description else "",
                        "image": _extract_image(item),
                    }
                )
    except ElementTree.ParseError:
        pass
    return articles


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation/stopwords and digits for near-duplicate matching."""
    t = re.sub(r"[^a-z0-9 ]", " ", title.lower())
    words = [
        w
        for w in t.split()
        if w
        not in {
            "the",
            "a",
            "an",
            "to",
            "of",
            "in",
            "on",
            "for",
            "with",
            "and",
            "or",
            "as",
            "at",
            "by",
            "from",
            "is",
            "are",
            "was",
            "will",
            "its",
            "it",
            "s",
            "t",
            "after",
            "before",
            "into",
            "over",
            "under",
            "vs",
        }
    ]
    return " ".join(words)


def cluster_articles(articles: list[dict]) -> list[dict]:
    """Group the same story covered by multiple sources.

    Uses token-set Jaccard similarity on normalized titles; returns clusters
    sorted by heat (number of distinct sources).
    """
    if not articles:
        return []
    normalized = [(a, _normalize_title(a.get("title", "")).split()) for a in articles]

    clusters: list[list] = []
    for art, toks in normalized:
        if not toks:
            continue
        tok_set = set(toks)
        best = None
        best_score = 0.0
        for ci, cluster in enumerate(clusters):
            c_toks = cluster[0]["_toks"]
            inter = len(tok_set & c_toks)
            union = len(tok_set | c_toks)
            score = inter / union if union else 0
            # require a strong overlap and share at least one real token
            if score > best_score and score >= 0.55 and inter >= 2:
                best = ci
                best_score = score
        if best is None:
            clusters.append([{"_toks": tok_set, **art}])
        else:
            clusters[best].append({"_toks": tok_set, **art})

    out = []
    for cluster in clusters:
        cluster.sort(key=lambda a: a.get("published", ""), reverse=True)
        lead = cluster[0]
        sources = sorted({a.get("source", "") for a in cluster})
        tickers = set()
        for a in cluster:
            tickers.update(extract_tickers(a.get("title", "") or ""))
        out.append(
            {
                "title": lead.get("title", ""),
                "url": lead.get("url", ""),
                "image": lead.get("image", ""),
                "published": lead.get("published", ""),
                "sentiment": lead.get("sentiment", "neutral"),
                "heat": len(sources),
                "sources": sources,
                "tickers": sorted(tickers),
                "article_count": len(cluster),
            }
        )
    out.sort(key=lambda c: (c["heat"], c["article_count"]), reverse=True)
    return out


def _sentiment_from_headline(title: str) -> str:
    title_lower = title.lower()
    bullish_words = [
        "surge",
        "rally",
        "gain",
        "rise",
        "jump",
        "soar",
        "bull",
        "upgrade",
        "beat",
        "record high",
        "boom",
        "profit",
        "optimism",
        "recovery",
        "outperform",
        "breakout",
    ]
    bearish_words = [
        "crash",
        "drop",
        "fall",
        "plunge",
        "sink",
        "bear",
        "downgrade",
        "miss",
        "loss",
        "slump",
        "recession",
        "fear",
        "sell-off",
        "selloff",
        "warning",
        "risk",
        "collapse",
        "bankrupt",
    ]

    b_count = sum(1 for w in bullish_words if w in title_lower)
    s_count = sum(1 for w in bearish_words if w in title_lower)

    if b_count > s_count:
        return "bullish"
    elif s_count > b_count:
        return "bearish"
    return "neutral"


async def fetch_news() -> dict:
    now = time.time()
    cache_key = "news"
    if cache_key in _cache and now - _cache[cache_key]["_ts"] < _cache_ttl.get(
        cache_key, 25
    ):
        return {k: v for k, v in _cache[cache_key].items() if k != "_ts"}

    all_articles = []
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:

        async def fetch_one(name: str, url: str):
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    return _parse_rss(resp.text, name)
            except Exception:
                pass
            return []

        tasks = [fetch_one(name, url) for name, url in NEWS_FEEDS.items()]
        results = await asyncio.gather(*tasks)
        for r in results:
            all_articles.extend(r)

    for a in all_articles:
        a["sentiment"] = _sentiment_from_headline(a["title"])
        a["tickers"] = extract_tickers(a.get("title", "") or "")

    seen_titles = set()
    unique = []
    for a in all_articles:
        t = a["title"].lower().strip()
        if t not in seen_titles:
            seen_titles.add(t)
            unique.append(a)

    unique.sort(key=lambda x: x.get("published", ""), reverse=True)

    result = {
        "articles": unique[:100],
        "total": len(unique),
        "sources": list(NEWS_FEEDS.keys()),
        "trending": cluster_articles(unique)[:8],
        "updated_at": now,
    }
    result["_ts"] = now
    _cache[cache_key] = result
    _cache_ttl[cache_key] = 25

    return {k: v for k, v in result.items() if k != "_ts"}
