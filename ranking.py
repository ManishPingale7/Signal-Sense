"""Transparent editorial scores; observed coverage is not independent verification."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlsplit

WEIGHTS = {"impact": 25, "novelty": 20, "attention": 20, "evidence": 15,
           "ecosystem": 10, "relevance": 5, "freshness": 5}
MAJOR_PLAYERS = {"openai", "anthropic", "google", "deepmind", "meta", "microsoft",
                 "nvidia", "amazon", "apple", "alibaba", "deepseek", "mistral", "xai", "x.ai"}
GENERIC = {"ai", "artificial intelligence", "model", "models", "llm", "agent", "agents",
           "open source", "benchmark", "benchmarks", "research", "technology", "release"}


def normalized(text):
    return " ".join(re.sub(r"[^a-z0-9.]+", " ", str(text).lower()).split())


def source_group(url):
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for group, hosts in {
        "google": ("google.com", "blog.google", "deepmind.google", "googleblog.com"),
        "microsoft": ("microsoft.com", "microsoft.ai"),
        "meta": ("meta.com", "fb.com"),
        "openai": ("openai.com",),
        "anthropic": ("anthropic.com",),
    }.items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return group
    # Blogs on shared platforms count by tenant, rather than all as one publisher.
    if host.endswith((".substack.com", ".github.io")):
        return host
    if host in ("github.com", "huggingface.co"):
        return host + "/" + urlsplit(url).path.strip("/").split("/")[0]
    bits = host.split(".")
    if len(bits) > 2 and ".".join(bits[-2:]) in ("co.uk", "com.au", "co.in"):
        return ".".join(bits[-3:])
    return ".".join(bits[-2:])


def coverage_rows(items):
    rows = {}
    for item in items:
        for row in item.get("coverage_records", [item]):
            if row.get("url"):
                rows.setdefault(row["url"], row)
    return list(rows.values())


def coverage_signal(items):
    rows = coverage_rows(items)
    parents, accepted = {}, []

    def root(group):
        parents.setdefault(group, group)
        while parents[group] != group:
            parents[group] = parents[parents[group]]
            group = parents[group]
        return group

    for row in sorted(rows, key=lambda r: r.get("url", "")):
        group = source_group(row["url"])
        if not group:
            continue
        root(group)
        title, summary = normalized(row.get("title", "")), normalized(row.get("summary", ""))
        for old_group, old_title, old_summary in accepted:
            copied = ((len(title) > 35 and title == old_title)
                      or (len(summary) > 160 and len(old_summary) > 160
                          and SequenceMatcher(None, summary[:600], old_summary[:600]).ratio() > .92))
            if copied:
                left, right = sorted((root(group), root(old_group)))
                parents[right] = left
        # Retain every fingerprint: a second URL from one publisher can reveal a copied story.
        accepted.append((group, title, summary))
    groups = {root(group) for group in parents}
    return {"source_count": len(groups), "source_groups": sorted(groups),
            "observed_domains": sorted({urlsplit(r["url"]).hostname for r in rows}),
            "urls": [r["url"] for r in rows], "suspected_copies_discounted": len(parents) - len(groups)}


def rank_event(judgment, items, corpus, now=None):
    now = now or datetime.now(timezone.utc)
    coverage = coverage_signal(items)
    entities = [e.strip()[:65] for e in judgment.get("entities", [])
                if len(e.strip()) >= 3 and normalized(e) not in GENERIC][:4]
    frequencies = []
    documents = coverage_rows(corpus)
    for entity in entities:
        pattern = re.compile(r"(?<!\w)" + re.escape(entity) + r"(?!\w)", re.I)
        hits = [r for r in documents if pattern.search(r.get("title", "") + " " + r.get("summary", "")[:500])]
        signal = coverage_signal(hits)
        frequencies.append({"keyword": entity, "source_count": signal["source_count"]})
    # Saturation prevents a heavily covered event from overwhelming significance.
    event_attention = min(100, 100 * math.log2(max(1, coverage["source_count"])) / math.log2(8))
    topic_count = max([f["source_count"] for f in frequencies] or [0])
    topic_attention = min(100, 100 * math.log2(max(1, topic_count)) / math.log2(12))
    components = {key: max(0, min(5, float(judgment.get(key, 0)))) * 20
                  for key in ("impact", "novelty", "evidence", "ecosystem", "relevance")}
    players = [p for p in judgment.get("players", []) if normalized(p) in MAJOR_PLAYERS]
    if players:
        components["ecosystem"] = max(80, components["ecosystem"])
    components["attention"] = round(event_attention * .8 + topic_attention * .2, 1)
    ages = []
    for item in items:
        try:
            stamp = datetime.fromisoformat(item["published"].replace("Z", "+00:00"))
            ages.append(max(0, (now - stamp).total_seconds() / 86400))
        except (ValueError, TypeError, KeyError):
            pass
    components["freshness"] = round(max(0, 100 * (1 - min(ages or [7]) / 7)), 1)
    contributions = {key: round(components[key] * weight / 100, 1) for key, weight in WEIGHTS.items()}
    score = round(sum(contributions.values()), 1)
    return {"score": score, "label": "High priority" if score >= 70 else "Worth knowing",
            "components": components, "contributions": contributions, "weights": WEIGHTS,
            "coverage": coverage, "keyword_frequency": frequencies, "major_players": players,
            "reason": judgment.get("reason", ""),
            "method": "Editorial priority, not factual confidence. Model judgments plus observed discovery signals; source grouping and copy discounts are heuristic."}
