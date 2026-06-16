import requests
import feedparser
import logging

logger = logging.getLogger("news_fetcher")

SOURCES = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss"
]

def get_news_summary() -> str:
    """Fetch & format crypto news for AI prompt context with strict timeout."""
    collected = []
    logger.info("📡 Mengambil berita terbaru dari RSS feeds...")
    for url in SOURCES:
        try:
            # Strict timeout 3.0s total per source
            resp = requests.get(url, timeout=3.0)
            feed = feedparser.parse(resp.content)
            
            for entry in feed.entries[:3]: # Top 3 per source
                title = entry.get('title', 'N/A')
                # Clean summary (remove tags, trim to 200 chars)
                summary = entry.get('summary', '')[:200].split('<')[0].strip()
                collected.append(f"Headline: {title}\nBrief: {summary}...")
        except Exception as e:
            logger.warning(f"⚠️ Gagal mengambil berita dari {url}: {e}")
            continue

    if not collected:
        return "Tidak ada berita terbaru yang tersedia saat ini."
    
    return "\n\n".join(collected)
