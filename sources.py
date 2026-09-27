"""Broad, bounded discovery of AI announcements and news. No paper collectors."""
from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from memory import same_story

HEADERS = {"User-Agent": "SignalAndSense/0.3 (public AI news reader)"}
TIMEOUT = (5, 15)
MAX_BYTES = 4_000_000
ATOM = "{http://www.w3.org/2005/Atom}"
PRIMARY_HOSTS = ("openai.com", "anthropic.com", "blog.google", "deepmind.google",
                 "mistral.ai", "typesafe.ai", "ai.meta.com", "x.ai", "qwen.ai")
FEEDS = (
    ("OpenAI announcements", "https://openai.com/news/rss.xml", "official"),
    ("Google AI announcements", "https://blog.google/technology/ai/rss/", "official"),
    ("Hugging Face releases", "https://huggingface.co/blog/feed.xml", "official"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "publisher"),
    ("TechCrunch AI page 2", "https://techcrunch.com/category/artificial-intelligence/feed/?paged=2", "publisher"),
    ("TechCrunch AI page 3", "https://techcrunch.com/category/artificial-intelligence/feed/?paged=3", "publisher"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "publisher"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "publisher"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "publisher"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", "commentary"),
    ("Latent Space", "https://www.latent.space/feed", "commentary"),
    ("Interconnects", "https://www.interconnects.ai/feed", "commentary"),
)
NEWS_QUERIES = (
    "AI model launch OpenAI Anthropic",
    "new AI models released this week",
    "open source open weight AI model release",
    "AI benchmark frontier model announcement",
    "new AI products agents launch",
    "AI emerging trends classification models",
)
HN_QUERIES = ("AI", "Claude", "GPT", "open source model", "Gemini", "classification")
PAPER_HOSTS = ("arxiv.org", "openreview.net", "aclanthology.org",
               "semanticscholar.org", "paperswithcode.com")
AI_TERMS = re.compile(r"\b(ai|llm|gpt|claude|gemini|anthropic|openai|llama|qwen|"
                      r"deepseek|mistral|classifier|classification|chatgpt|machine learning|"
                      r"artificial intelligence|open.weight|language model)\b", re.I)


def _clean(value):
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _plain(value):
    return _clean(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True))


def _iso(value):
    if not value:
        return ""
    text = str(value).strip()
    for parse in (
        lambda: datetime.fromisoformat(text.replace("Z", "+00:00")),
        lambda: parsedate_to_datetime(text),
        lambda: datetime.strptime(text, "%b %d, %Y"),
        lambda: datetime.strptime(text, "%B %d, %Y"),
    ):
        try:
            stamp = parse()
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            pass
    return ""  # Never invent a publication date.


def _recent(stamp):
    try:
        date = datetime.fromisoformat(stamp)
        now = datetime.now(timezone.utc)
        return now - timedelta(days=7) <= date <= now + timedelta(minutes=5)
    except (ValueError, TypeError):
        return False


def is_paper_link(url):
    parsed = urlsplit(url)
    host, path = (parsed.hostname or "").lower(), parsed.path.lower()
    return (any(host == x or host.endswith("." + x) for x in PAPER_HOSTS)
            or (host.endswith("huggingface.co") and (path == "/papers" or path.startswith("/papers/")))
            or path.endswith(".pdf"))


def _safe_url(url):
    """Validate each public destination, including redirects, before fetching it."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.port not in (None, 443) or is_paper_link(url)):
        raise ValueError("Source must be a public HTTPS news page, not a paper")
    host = parsed.hostname.lower()
    if "." not in host or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Non-public source host")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("Non-public source address")


def _get(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    for _ in range(5):
        _safe_url(url)
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                          allow_redirects=False, stream=True) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            response.raise_for_status()
            chunks, total = [], 0
            for chunk in response.iter_content(32768):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("Source exceeded the reader size limit")
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("content-type", ""), url
    raise ValueError("Too many source redirects")


def _canonical(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    # Bing's RSS links wrap the real publisher URL. Decode without fetching the wrapper.
    if (parsed.hostname or "").endswith("bing.com") and query.get("url"):
        return _canonical(query["url"][0])
    if parsed.scheme == "http":
        parsed = parsed._replace(scheme="https")
    kept = {k: v for k, v in query.items()
            if not k.lower().startswith("utm_") and k.lower() not in ("ref", "fpr")}
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"),
                      urlencode(kept, doseq=True), ""))


def _record(title, url, summary, date, source, channel, *, date_basis="published",
            points=0, comments=0, search_query="", evidence_kind="publisher excerpt"):
    url = _canonical(url)
    if not title or not url.startswith("https://") or is_paper_link(url):
        return None
    host = urlsplit(url).hostname or ""
    official = channel == "official" or host in PRIMARY_HOSTS or host.removeprefix("www.") in PRIMARY_HOSTS
    return {
        "title": _plain(title)[:350], "url": url, "summary": _plain(summary)[:2200],
        "published": _iso(date), "date_basis": date_basis, "source": source or host,
        "kind": "News", "channel": channel, "official": official,
        "points": max(0, int(points or 0)), "comments": max(0, int(comments or 0)),
        "discovered_via": [channel], "search_queries": [search_query] if search_query else [],
        "evidence_kind": evidence_kind, "related_sources": [],
    }


def feed(url, name, channel, search_query=""):
    content, _, final_url = _get(url)
    root = ET.fromstring(content)
    records = []
    nodes = root.findall(".//item") or root.findall(ATOM + "entry")
    for node in nodes[:150]:
        atom = node.tag == ATOM + "entry"
        prefix = ATOM if atom else ""
        title = node.findtext(prefix + "title", "")
        if atom:
            link = next((x.get("href", "") for x in node.findall(ATOM + "link")
                         if x.get("rel", "alternate") == "alternate"), "")
            date = node.findtext(ATOM + "published") or node.findtext(ATOM + "updated")
            summary = node.findtext(ATOM + "summary") or node.findtext(ATOM + "content", "")
        else:
            link = node.findtext("link", "")
            date = node.findtext("pubDate") or node.findtext("{http://purl.org/dc/elements/1.1/}date")
            summary = node.findtext("description", "")
        publisher = next((x.text for x in node if x.tag.rsplit("}", 1)[-1] == "Source"), name)
        record = _record(title, urljoin(final_url, link), summary, date, publisher, channel,
                         search_query=search_query,
                         evidence_kind="search snippet" if channel == "web search" else "publisher excerpt")
        if record and _recent(record["published"]):
            if name in ("Ars Technica", "Simon Willison") and not AI_TERMS.search(title + " " + _plain(summary)[:500]):
                continue
            records.append(record)
    return records


def news_search(query):
    url = "https://www.bing.com/news/search?" + urlencode(
        {"q": query[:180], "format": "rss", "count": 30, "setlang": "en"})
    return feed(url, "Bing News", "web search", search_query=query[:180])


def hn_search(query):
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
    content, _, _ = _get("https://hn.algolia.com/api/v1/search", {
        "query": query[:120], "tags": "story", "hitsPerPage": 40,
        "numericFilters": f"created_at_i>{cutoff}",
    })
    result = []
    for item in json.loads(content).get("hits", []):
        record = _record(item.get("title"), item.get("url") or "", "",
                         item.get("created_at"), urlsplit(item.get("url") or "").hostname,
                         "community", date_basis="discovered", points=item.get("points"),
                         comments=item.get("num_comments"), search_query=query,
                         evidence_kind="discussion title only")
        if record and _recent(record["published"]):
            result.append(record)
    return result


def anthropic_news():
    content, _, url = _get("https://www.anthropic.com/news")
    soup = BeautifulSoup(content, "html.parser")
    records = []
    for anchor in soup.select("a[href]"):
        time = anchor.find("time")
        if time is None:
            continue
        title = anchor.find(["h2", "h3", "h4"]) or anchor.select_one('[class*="title"]')
        if title is None:
            continue
        summary = anchor.find("p")
        item = _record(title.get_text(" ", strip=True), urljoin(url, anchor["href"]),
                       summary.get_text(" ", strip=True) if summary else "",
                       time.get("datetime") or time.get_text(" ", strip=True),
                       "Anthropic", "official")
        if item and _recent(item["published"]):
            records.append(item)
    return records


def _query_terms(query):
    # A watch list like "Jev, Laya; zero-shot classification" becomes separate searches.
    return list(dict.fromkeys(part.strip()[:150] for part in re.split(r"[,;\n]+", query or "")
                              if part.strip()))[:4]


def _jobs(jobs, log=None):
    records, errors, coverage = [], [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(fn): (name, channel) for name, channel, fn in jobs}
        for future in as_completed(pending):
            name, channel = pending[future]
            try:
                items = future.result()
                records.extend(items)
                coverage.append({"name": name, "channel": channel, "status": "ok",
                                 "recent_results": len(items)})
                if log:
                    log("collect", name, f"{len(items)} results from the past seven days")
            except Exception as exc:
                # Do not surface raw exception URLs, headers, or credentials.
                reason = type(exc).__name__
                errors.append(f"{name}: {reason}")
                coverage.append({"name": name, "channel": channel, "status": "unavailable",
                                 "recent_results": 0})
                if log:
                    log("warning", name + " unavailable", reason + "; continuing with other sources")
    return records, errors, sorted(coverage, key=lambda x: x["name"])


def collect(query="", log=None):
    jobs = [(name, channel, lambda u=url, n=name, c=channel: feed(u, n, c))
            for name, url, channel in FEEDS]
    jobs.append(("Anthropic newsroom", "official", anthropic_news))
    for query_text in (*NEWS_QUERIES, *_query_terms(query)):
        jobs.append(("News search: " + query_text, "web search",
                     lambda q=query_text: news_search(q)))
    for query_text in (*HN_QUERIES, *_query_terms(query)):
        jobs.append(("Community search: " + query_text, "community",
                     lambda q=query_text: hn_search(q)))
    return _jobs(jobs, log)


def collect_extra(queries, log=None):
    jobs = []
    for query in list(dict.fromkeys(queries))[:4]:
        query = _clean(query)[:180]
        if not query:
            continue
        jobs.append(("Follow-up news: " + query, "web search", lambda q=query: news_search(q)))
        jobs.append(("Follow-up community: " + query, "community", lambda q=query: hn_search(q)))
    return _jobs(jobs, log)


def combine(records):
    """Merge duplicate coverage while preserving real discovery signals."""
    unique = []
    for item in records:
        if not _recent(item.get("published")) or is_paper_link(item["url"]):
            continue
        other = next((x for x in unique if same_story(item, x)), None)
        if other is None:
            unique.append({**item, "coverage_records": list(item.get("coverage_records", [dict(item)]))})
            continue
        coverage_records = [*other.get("coverage_records", [dict(other)]), *item.get("coverage_records", [dict(item)])]
        references = [*other.get("related_sources", []), *item.get("related_sources", [])]
        if item["url"] != other["url"]:
            references.append({"title": item["title"], "url": item["url"], "source": item["source"]})
        via = list(dict.fromkeys([*other["discovered_via"], *item["discovered_via"]]))
        queries = list(dict.fromkeys([*other["search_queries"], *item["search_queries"]]))
        points, comments = max(other["points"], item["points"]), max(other["comments"], item["comments"])
        quality = lambda x: (x["official"], x["date_basis"] == "published",
                             x["evidence_kind"] != "search snippet", len(x["summary"]))
        if quality(item) > quality(other):
            if item["url"] != other["url"]:
                references.append({"title": other["title"], "url": other["url"], "source": other["source"]})
            other.update(item)
        other.update(discovered_via=via, search_queries=queries, points=points, comments=comments,
                     coverage_records=list({x["url"]: x for x in coverage_records}.values()))
        other["related_sources"] = list({x["url"]: x for x in references if x["url"] != other["url"]}.values())[:6]
    return unique


def score(item, watch=""):
    text = item["title"].lower()
    value = 5 if item["official"] else 0
    value += min(9, math.log2(item["points"] + 1))
    value += min(4, math.log2(item["comments"] + 1) / 2)
    value += min(3, len(item["discovered_via"]) - 1)
    if re.search(r"\b(introducing|launch|launches|released|release|unveils|open.weight|open.source|frontier|benchmark)\b", text):
        value += 4
    if re.search(r"\b(sdk|plugin|tutorial|how to|integration|workshop|webinar)\b", text):
        value -= 4
    if any(term.lower() in text for term in _query_terms(watch)):
        value += 8
    return value


def shortlist(records, watch="", limit=120):
    ranked = sorted(combine(records), key=lambda x: (score(x, watch), x["published"]), reverse=True)
    # Reserve space for each major discovery channel before filling by significance.
    chosen = []
    for channel in ("official", "web search", "publisher", "community", "commentary"):
        chosen.extend([x for x in ranked if x["channel"] == channel][:12])
    seen = {x["url"] for x in chosen}
    chosen.extend(x for x in ranked if x["url"] not in seen)
    return sorted(chosen[:limit], key=lambda x: (score(x, watch), x["published"]), reverse=True)


def read_article(url):
    content, content_type, final_url = _get(url)
    if "html" not in content_type.lower():
        raise ValueError("Source is not an HTML news article")
    soup = BeautifulSoup(content, "html.parser")
    published = ""
    for selector in ('meta[property="article:published_time"]', 'meta[name="date"]',
                     'meta[name="pubdate"]', 'meta[itemprop="datePublished"]'):
        node = soup.select_one(selector)
        if node:
            published = _iso(node.get("content"))
            if published:
                break
    def find_date(value):
        if isinstance(value, dict):
            if value.get("datePublished"):
                return _iso(value["datePublished"])
            for key in ("@graph", "mainEntity"):
                if key in value:
                    result = find_date(value[key])
                    if result:
                        return result
        elif isinstance(value, list):
            for entry in value:
                result = find_date(entry)
                if result:
                    return result
        return ""
    if not published:
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                published = find_date(json.loads(node.string or node.get_text()))
            except (ValueError, TypeError):
                continue
            if published:
                break
    for node in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        node.decompose()
    body = soup.find("article") or soup.find("main") or soup.body or soup
    text = _clean(body.get_text(" ", strip=True))
    # Common interstitials are not article evidence.
    if len(text) < 300 or (len(text) < 2000 and re.search(
            r"verify you are human|enable javascript and cookies|checking your browser", text, re.I)):
        text = ""
    return {"url": final_url, "text": text[:10000], "published": published}


def open_article(url):
    return read_article(url)["text"]
