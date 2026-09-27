"""Local web app for the Signal & Sense demo."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import run, safe_error
from memory import history, remember
from typing import Literal

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
DATA = ROOT / "data"
LATEST = DATA / "latest.json"
DATA.mkdir(exist_ok=True)

app = FastAPI(title="Signal & Sense")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
guard = threading.Lock()
cancel_event = threading.Event()
last_started = 0.0
state = {"status": "idle", "activity": [], "error": None, "started_at": None}


class Preferences(BaseModel):
    topics: list[str] = Field(default_factory=lambda: ["agents", "models"])
    depth: Literal["quick", "explain", "technical"] = "explain"
    mode: Literal["weekly", "explore", "new"] = "weekly"  # Accept old clients; run maps new to weekly.
    context: str = Field(default="", max_length=1000)
    query: str = Field(default="", max_length=200)
    max_updates: int = Field(default=15, ge=1, le=25)


def _load_latest() -> dict | None:
    if not LATEST.exists():
        return None
    try:
        return json.loads(LATEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _activity(kind: str, title: str, detail: str) -> None:
    if cancel_event.is_set():
        raise InterruptedError("Run cancelled")
    entry = {"kind": kind, "title": title, "detail": detail,
             "at": datetime.now().strftime("%H:%M:%S")}
    with guard:
        state["activity"].append(entry)


def _worker(preferences: dict) -> None:
    try:
        briefing = run(preferences, _activity)
        with guard:
            briefing["activity"] = list(state["activity"])
        if cancel_event.is_set():
            raise InterruptedError("Run cancelled")
        remember(briefing)
        target = LATEST.with_suffix(".tmp")
        target.write_text(json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8")
        target.replace(LATEST)
        _activity("saved", "Briefing saved", f"{len(briefing['stories'])} updates ready to explore or present")
        with guard:
            state["status"] = "complete"
    except InterruptedError:
        with guard:
            state["status"] = "cancelled"
            state["error"] = None
            state["activity"].append({"kind": "warning", "title": "Run cancelled",
                "detail": "Your saved briefings are still available.", "at": datetime.now().strftime("%H:%M:%S")})
    except Exception as exc:
        message = safe_error(exc)
        with guard:
            state["status"] = "error"
            state["error"] = message
            state["activity"].append({"kind": "error", "title": "The run stopped",
                "detail": message, "at": datetime.now().strftime("%H:%M:%S")})


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/state")
def get_state():
    with guard:
        snapshot = dict(state)
        snapshot["activity"] = list(state["activity"])
    snapshot["briefing"] = _load_latest()
    snapshot["configured"] = bool(os.getenv("GEMINI_API_KEY"))
    snapshot["teams_configured"] = bool(os.getenv("TEAMS_WEBHOOK_URL"))
    return snapshot


@app.get("/api/history")
def get_history():
    return {"briefings": history()[:50]}


@app.post("/api/run")
def start_run(preferences: Preferences):
    global last_started
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=400, detail="Set GEMINI_API_KEY and restart the app first.")
    with guard:
        if state["status"] in ("running", "cancelling"):
            raise HTTPException(status_code=409, detail="A briefing is already being generated.")
        if time.monotonic() - last_started < 15:
            raise HTTPException(status_code=429, detail="Wait a few seconds before starting another run.")
        last_started = time.monotonic()
        cancel_event.clear()
        state.update(status="running", activity=[], error=None,
                     started_at=datetime.now().isoformat())
    threading.Thread(target=_worker, args=(preferences.model_dump(),), daemon=True).start()
    return {"status": "running"}



@app.get("/api/health")
def health():
    return {"app": "signal-and-sense", "version": "demo-2"}


@app.post("/api/cancel")
def cancel_run():
    with guard:
        if state["status"] == "running":
            cancel_event.set()
            state["status"] = "cancelling"
    return {"status": state["status"]}


class DemoChoice(BaseModel):
    briefing_id: str = Field(min_length=1, max_length=100)


def _demo_briefing():
    pinned = DATA / "demo.json"
    if pinned.exists():
        try:
            value = json.loads(pinned.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("stories"):
                return value
        except (ValueError, OSError):
            pass
    bundled = ROOT / "demo" / "briefing.json"
    if bundled.exists():
        try:
            value = json.loads(bundled.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("stories"):
                return value
        except (ValueError, OSError):
            pass
    available = [b for b in history() if b.get("stories")]
    return max(available, key=lambda b: (len(b["stories"]), b.get("generated_at", "")), default=None)


@app.get("/api/demo")
def demo():
    return {"briefing": _demo_briefing(), "saved_demo": True}


@app.post("/api/demo")
def pin_demo(choice: DemoChoice):
    selected = next((b for b in history() if b["id"] == choice.briefing_id), None)
    if not selected or not selected.get("stories"):
        raise HTTPException(status_code=400, detail="Choose a saved briefing containing stories.")
    target = DATA / "demo.tmp"
    target.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    target.replace(DATA / "demo.json")
    return {"saved": True, "briefing_id": selected["id"]}


@app.post("/api/send-teams")
def send_teams():
    webhook = os.getenv("TEAMS_WEBHOOK_URL", "")
    if not webhook.startswith("https://"):
        raise HTTPException(status_code=400, detail="Set TEAMS_WEBHOOK_URL to a Teams Workflows webhook.")
    briefing = _load_latest()
    if not briefing:
        raise HTTPException(status_code=400, detail="Generate a briefing first.")
    lines = ["Signal & Sense | AI Morning Brief", briefing["opening"], ""]
    for number, story in enumerate(briefing["stories"], 1):
        lines.extend([f"{number}. {story['title']}", story["deck"],
                      f"Why it matters: {story['why_it_matters']}", story["url"], ""])
    try:
        response = requests.post(webhook, json={"text": "\n".join(lines)}, timeout=12)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Teams did not accept the message. Check the webhook setup and try again.") from exc
    # Sharing does not change the generation state.
    return {"sent": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
