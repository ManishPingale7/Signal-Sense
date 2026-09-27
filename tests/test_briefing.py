"""Offline regression checks. No network, model calls or Teams messages."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import build_briefing, Review, WrittenBrief, safe_error, BriefingError
from ranking import rank_event, coverage_signal, source_group
from sources import combine


def item(n, **extras):
    return dict({
        "title": f"Aurora model edition {n} launches",
        "url": f"https://publisher{n}.example/news/{n}",
        "summary": "", "published": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "date_basis": "published", "source": f"Publisher {n}", "kind": "News",
        "channel": "web search", "official": False, "points": 0, "comments": 0,
        "discovered_via": ["web search"], "search_queries": [],
        "evidence_kind": "search snippet", "related_sources": [],
    }, **extras)


class Harness:
    def __init__(self, records, extra=None, fail_reads=None, omit_once=False, unsupported_once=False):
        self.records = records
        self.extra = extra or []
        self.fail_reads = fail_reads or set()
        self.omit_once = omit_once
        self.unsupported_once = unsupported_once
        self.searches = 0
        self.writes = 0
        self.events = []

    def log(self, kind, title, detail):
        self.events.append((kind, title, detail))

    def discover(self, **kwargs):
        return self.records[:], [], [{"name": "offline fixture", "status": "ok", "recent_results": len(self.records)}]

    def search(self, queries, **kwargs):
        self.searches += 1
        return (self.extra[:] if self.searches == 1 else []), [], []

    def read(self, url):
        if url in self.fail_reads:
            raise OSError("Fixture inaccessible")
        return {"url": url, "text": "Source evidence. " * 80, "published": ""}

    def ask(self, prompt, schema):
        if schema is Review:
            catalog = json.loads(prompt[prompt.index('{"mode":'):])["CATALOG"]
            return Review(events=[{
                "indices": [row["index"]], "event_key": row["title"],
                "reason": "A useful release supported by the catalog.", "significance": "major",
                "category": "model", "impact": 5, "novelty": 5, "evidence": 5,
                "ecosystem": 5, "relevance": 5, "players": [], "entities": ["Aurora"],
            } for row in catalog])
        self.writes += 1
        inputs = json.loads(prompt[prompt.index('{"project_context":'):])["SOURCES"]
        stories = []
        for i, row in enumerate(inputs):
            if self.omit_once and self.writes == 1 and i == 0:
                continue
            supported = not (self.unsupported_once and self.writes == 1 and i == 0)
            stories.append({
                "index": row["index"], "deck": "A supported update.", "summary": "A useful new release.",
                "why_it_matters": "New capabilities.", "topics": ["models"], "next_step": "",
                "evidence": "Fixture source.", "novelty": "A new release.",
                "supported": supported, "exclusion_reason": "" if supported else "Insufficient evidence.",
            })
        return WrittenBrief(stories=stories)

    def run(self, target=15):
        return build_briefing({"max_updates": target}, self.log, self.ask,
                              discover=self.discover, search=self.search, reader=self.read)


class BriefingTests(unittest.TestCase):
    def test_exact_requested_count_and_ranking(self):
        h = Harness([item(i) for i in range(20)])
        result = h.run()
        self.assertEqual(len(result["stories"]), 15)
        self.assertTrue(result["target_met"])
        scores = [s["ranking"]["score"] for s in result["stories"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertLessEqual(sum(s["section"] == "lead" for s in result["stories"]), 5)

    def test_unreadable_sources_replaced_from_reserves(self):
        records = [item(i) for i in range(20)]
        h = Harness(records, fail_reads={x["url"] for x in records[:3]})
        result = h.run()
        self.assertEqual(len(result["stories"]), 15)
        self.assertTrue(all(s["url"] not in h.fail_reads for s in result["stories"]))

    def test_writer_rejection_is_replaced(self):
        result = Harness([item(i) for i in range(20)], unsupported_once=True).run()
        self.assertEqual(len(result["stories"]), 15)

    def test_omitted_writer_item_retried(self):
        h = Harness([item(i) for i in range(15)], omit_once=True)
        result = h.run()
        self.assertEqual(len(result["stories"]), 15)
        self.assertEqual(h.writes, 4)

    def test_followup_search_fills_target(self):
        h = Harness([item(i) for i in range(5)], extra=[item(i) for i in range(5, 20)])
        result = h.run()
        self.assertEqual(len(result["stories"]), 15)
        self.assertEqual(h.searches, 1)

    def test_shortfall_is_explicit_after_search_budget(self):
        h = Harness([item(i) for i in range(2)])
        result = h.run(10)
        self.assertEqual(len(result["stories"]), 2)
        self.assertFalse(result["target_met"])
        self.assertIn("2 of 10", result["shortfall_reason"])
        self.assertEqual(h.searches, 2)

    def test_outside_window_sources_not_published(self):
        h = Harness([item(i) for i in range(3)])
        h.read = lambda url: {"url": url, "text": "x" * 400,
                             "published": (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()}
        with self.assertRaises(BriefingError):
            h.run(2)

    def test_provider_error_preserves_partial_result(self):
        h = Harness([item(i) for i in range(15)])
        original = h.ask
        def fail_second_batch(prompt, schema):
            if schema is WrittenBrief and h.writes == 1:
                raise TimeoutError()
            return original(prompt, schema)
        h.ask = fail_second_batch
        result = h.run()
        self.assertEqual(len(result["stories"]), 5)
        self.assertIn("timed out", result["shortfall_reason"])

    def test_all_sources_down_stops_safely(self):
        h = Harness([])
        h.discover = lambda **kwargs: ([], ["unavailable"], [{"status": "unavailable"}])
        with self.assertRaises(BriefingError):
            h.run()

    def test_cancel_propagates(self):
        h = Harness([item(1)])
        h.read = lambda url: (_ for _ in ()).throw(InterruptedError())
        with self.assertRaises(InterruptedError):
            h.run(1)


class RankingTests(unittest.TestCase):
    def test_coverage_preserved_after_duplicate_merge(self):
        first = item(1)
        other = item(1, url="https://another.example/story")
        combined = combine([first, other, first])
        self.assertEqual(len(combined), 1)
        self.assertEqual(len(combined[0]["coverage_records"]), 2)

    def test_copies_and_same_domain_do_not_inflate_coverage(self):
        a = item(1, title="Announcing the remarkable Aurora latest model release")
        b = item(2, title=a["title"])
        c = item(3, url="https://publisher1.example/another", title="Other article about this launch")
        signal = coverage_signal([a, b, c])
        self.assertEqual(signal["source_count"], 1)
        self.assertEqual(signal["suspected_copies_discounted"], 1)

    def test_parent_source_grouping(self):
        self.assertEqual(source_group("https://blog.google/news"), source_group("https://deepmind.google/news"))
        self.assertNotEqual(source_group("https://one.substack.com/p/a"), source_group("https://two.substack.com/p/b"))

    def test_newcomer_can_outrank_major_player(self):
        strong = {"impact": 5, "novelty": 5, "evidence": 5, "ecosystem": 4, "relevance": 4,
                  "players": ["NewCo"], "entities": []}
        minor = {"impact": 1, "novelty": 1, "evidence": 5, "ecosystem": 3, "relevance": 4,
                 "players": ["OpenAI"], "entities": []}
        self.assertGreater(rank_event(strong, [item(1)], [])["score"],
                           rank_event(minor, [item(2)], [])["score"])

    def test_errors_never_echo_credentials(self):
        self.assertNotIn("secret", safe_error(RuntimeError("API key=secret")))
        self.assertEqual(safe_error(BriefingError("Safe fixed message")), "Safe fixed message")


class AppTests(unittest.TestCase):
    def test_failed_run_keeps_previous_briefing(self):
        import app
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "latest.json"
            target.write_text('{"id":"previous","stories":[{"title":"Saved"}]}', encoding="utf-8")
            app.cancel_event.clear()
            with patch.object(app, "LATEST", target), patch.object(app, "run", side_effect=TimeoutError()):
                app._worker({})
                self.assertEqual(json.loads(target.read_text())["id"], "previous")
                self.assertEqual(app.state["status"], "error")

    def test_routes_and_demo_have_no_external_calls(self):
        import app
        from fastapi.testclient import TestClient
        with patch.object(app, "_demo_briefing", return_value={"id": "saved", "stories": [{"title": "Saved"}]}):
            client = TestClient(app.app)
            self.assertEqual(client.get("/api/health").json()["version"], "demo-2")
            self.assertEqual(client.get("/api/demo").json()["briefing"]["id"], "saved")
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/static/app.js").status_code, 200)
            self.assertEqual(client.post("/api/run", json={"max_updates": 26}).status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
