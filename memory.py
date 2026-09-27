"""Local briefing history and conservative duplicate matching."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent / "data"
ARCHIVE = ROOT / "history"


def history() -> list[dict]:
    paths = list(ARCHIVE.glob("*.json")) if ARCHIVE.exists() else []
    paths.append(ROOT / "latest.json")  # Includes briefings created before history existed.
    found = {}
    for path in paths:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(item, dict) and item.get("id"):
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
