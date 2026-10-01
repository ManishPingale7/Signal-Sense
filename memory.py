"""Local briefing history and conservative duplicate matching."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent / "data"
ARCHIVE = ROOT / "history"


def valid_briefing(item):
    """Reject corrupt saved data before it reaches the UI or Teams formatter."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
        return False
    if not isinstance(item.get("generated_at"), str) or not isinstance(item.get("opening"), str):
        return False
    stories = item.get("stories")
    return isinstance(stories, list) and bool(stories) and all(
        isinstance(story, dict) and all(isinstance(story.get(key), str) for key in
        ("title", "url", "deck", "summary", "why_it_matters", "evidence"))
        for story in stories)


def history() -> list[dict]:
    paths = list(ARCHIVE.glob("*.json")) if ARCHIVE.exists() else []
    paths.append(ROOT / "latest.json")  # Includes briefings created before history existed.
    found = {}
    for path in paths:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if valid_briefing(item):
                found[item["id"]] = item
        except (OSError, ValueError):
            continue
    return sorted(found.values(), key=lambda x: x.get("generated_at", ""), reverse=True)


def remember(briefing: dict) -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    # Preserve the previous latest file when migrating from the original demo.
    for item in [*history()[:1], briefing]:
        name = re.sub(r"[^A-Za-z0-9_-]", "", item["id"])
        target = ARCHIVE / (name + ".json")
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)


def identity(item: dict) -> str:
    url = urlsplit(item.get("url", ""))
    query = [(k, v) for k, v in parse_qsl(url.query)
             if not k.lower().startswith("utm_") and k.lower() not in ("ref", "fpr")]
    return (url.hostname or "").removeprefix("www.") + url.path.rstrip("/") + "?" + urlencode(sorted(query))


def same_story(a: dict, b: dict) -> bool:
    if identity(a) and identity(a) == identity(b):
        return True
    def title(item):
        return re.sub(r"[^a-z0-9 ]", " ", item.get("title", "").lower()).split()
    x, y = title(a), title(b)
    # Preserve version/number differences as potentially substantive developments.
    if {w for w in x if any(c.isdigit() for c in w)} != {w for w in y if any(c.isdigit() for c in w)}:
        return False
    return bool(x and y) and SequenceMatcher(None, " ".join(x), " ".join(y)).ratio() >= .86
