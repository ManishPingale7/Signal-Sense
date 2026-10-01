"""Offline failure matrix. No real credentials, providers, or Teams calls."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import BaseModel, ValidationError
import providers
import app
import memory
import sources
from agent import Event, WrittenStory
from fastapi.testclient import TestClient

class Answer(BaseModel):
    value: str

class RemoteError(Exception):
    def __init__(self, status):
        self.status_code = status
        super().__init__("SECRET credential in remote error " + str(status))

class FakeProvider(providers.Provider):
    outcomes = []
    instances = []
    def __init__(self):
        super().__init__("Fake", "fixture", 0)
        self.call = MagicMock(side_effect=list(type(self).outcomes))
        self.closed = False
        type(self).instances.append(self)
    def close(self):
        self.closed = True

class Backup(FakeProvider):
    outcomes = [Answer(value="backup")] * 30
    instances = []

class RoutingTests(unittest.TestCase):
    def setUp(self):
        providers._COOLDOWNS.clear()
        providers._REQUEST_TIMES.clear()
        FakeProvider.instances.clear()
        Backup.instances.clear()
        self.logs = []
        self.log = lambda *args: self.logs.append(args)
        self.env = patch.dict(os.environ, {"GEMINI_API_KEY": "fixture", "GROQ_API_KEY": "fixture"}, clear=True)
        self.env.start()
        self.mapping = patch.dict(providers._PROVIDER_KEYS, {
            "gemini": ("GEMINI_API_KEY", FakeProvider),
            "groq": ("GROQ_API_KEY", Backup),
        }, clear=True)
        self.mapping.start()
    def tearDown(self):
        self.mapping.stop()
        self.env.stop()
        providers._COOLDOWNS.clear()
        providers._REQUEST_TIMES.clear()
    def test_429_switches_provider_without_retrying_exhausted_one(self):
        FakeProvider.outcomes = [RemoteError(429)]
        router = providers.ProviderRouter(self.log)
        self.assertEqual(router.ask("", Answer).value, "backup")
        self.assertEqual(router.ask("", Answer).value, "backup")
        self.assertEqual(FakeProvider.instances[-1].call.call_count, 1)
        self.assertEqual(router.attempts, 3)
        self.assertNotIn("SECRET", repr(self.logs))
    def test_timeout_switches_provider(self):
        FakeProvider.outcomes = [TimeoutError("SECRET")]
        router = providers.ProviderRouter(self.log)
        self.assertEqual(router.ask("", Answer).value, "backup")
        self.assertIn("request timed out", repr(self.logs))
    def test_bad_credentials_switches_provider(self):
        FakeProvider.outcomes = [RemoteError(401)]
        self.assertEqual(providers.ProviderRouter(self.log).ask("", Answer).value, "backup")
        self.assertNotIn("SECRET", repr(self.logs))
    def test_invalid_json_switches_provider(self):
        FakeProvider.outcomes = [ValueError("invalid JSON SECRET")]
        self.assertEqual(providers.ProviderRouter(self.log).ask("", Answer).value, "backup")
    def test_cooldown_survives_new_router(self):
        FakeProvider.outcomes = [RemoteError(429)]
        providers.ProviderRouter(self.log).ask("", Answer)
        second = providers.ProviderRouter(self.log)
        second.ask("", Answer)
        self.assertEqual(FakeProvider.instances[-1].call.call_count, 0)
    def test_expired_cooldown_allows_next_run(self):
        FakeProvider.outcomes = [Answer(value="recovered")]
        providers._COOLDOWNS["gemini"] = -1
        self.assertEqual(providers.ProviderRouter(self.log).ask("", Answer).value, "recovered")
    def test_all_failed_not_retried(self):
        FakeProvider.outcomes = [RemoteError(429)]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fixture"}, clear=True):
            router = providers.ProviderRouter(self.log)
            for _ in range(2):
                with self.assertRaises(providers.ProviderUnavailable):
                    router.ask("", Answer)
            self.assertEqual(FakeProvider.instances[-1].call.call_count, 1)
    def test_mistral_only_routes_successfully(self):
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "fixture"}, clear=True), patch.dict(
            providers._PROVIDER_KEYS, {"mistral": ("MISTRAL_API_KEY", Backup)}, clear=True):
            router = providers.ProviderRouter(self.log)
            for task in ("review", "write", "unknown"):
                self.assertEqual(router.ask("", Answer, task).value, "backup")
    def test_attempt_budget_is_hard_limit(self):
        FakeProvider.outcomes = [Answer(value="ok")] * 30
        router = providers.ProviderRouter(self.log)
        for _ in range(providers.MAX_ATTEMPTS):
            router.ask("", Answer)
        with self.assertRaises(providers.ProviderUnavailable):
            router.ask("", Answer)
        self.assertEqual(router.attempts, providers.MAX_ATTEMPTS)
    def test_cancel_never_falls_back(self):
        FakeProvider.outcomes = [InterruptedError()]
        router = providers.ProviderRouter(self.log)
        with self.assertRaises(InterruptedError):
            router.ask("", Answer)
        Backup.instances[-1].call.assert_not_called()
    def test_cancel_during_pacing(self):
        provider = providers.Provider("fixture", "fixture", 10)
        providers._REQUEST_TIMES[provider.name] = providers.time.monotonic()
        def log(kind, *args):
            if kind == "checkpoint":
                raise InterruptedError()
        with patch.object(providers.time, "sleep"):
            with self.assertRaises(InterruptedError):
                provider.pace(log)
    def test_provider_initialization_does_not_leak_remote_error(self):
        with patch.dict(providers._PROVIDER_KEYS, {"gemini": ("GEMINI_API_KEY", MagicMock(side_effect=RuntimeError("SECRET")))}, clear=True):
            # Give the factory its display name, like real classes have.
            providers._PROVIDER_KEYS["gemini"][1].__name__ = "BrokenProvider"
            with self.assertRaises(RuntimeError):
                providers.ProviderRouter(self.log)
        self.assertNotIn("SECRET", repr(self.logs))
    def test_clients_are_closed(self):
        FakeProvider.outcomes = []
        router = providers.ProviderRouter(self.log)
        router.close()
        self.assertTrue(all(p.closed for p in router.providers.values()))
    def test_code_fences_are_accepted(self):
        self.assertEqual(Answer.model_validate_json(providers._clean_json_text('```json\n{"value":"ok"}\n```')).value, "ok")

class RobustAppTests(unittest.TestCase):
    def setUp(self):
        self.old_state = dict(app.state)
        self.old_started = app.last_started
        app.cancel_event.clear()
        app.state.update(status="idle", activity=[], error=None)
        app.last_started = 0
        self.client = TestClient(app.app)
    def tearDown(self):
        app.state.clear()
        app.state.update(self.old_state)
        app.last_started = self.old_started
        app.cancel_event.clear()
    def test_all_providers_unavailable_uses_bundled_demo(self):
        with patch.object(app, "_load_latest", return_value=None), patch.object(app, "run", side_effect=providers.ProviderUnavailable("SECRET")):
            app._worker({})
            result = self.client.get("/api/state").json()
            self.assertEqual(result["status"], "fallback")
            self.assertTrue(result["saved_demo"])
            self.assertGreater(len(result["briefing"]["stories"]), 0)
            self.assertNotIn("SECRET", result["error"])
    def test_saved_demo_needs_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(self.client.get("/api/demo").json()["briefing"]["stories"])
            self.assertEqual(self.client.post("/api/run", json={}).status_code, 400)
    def test_duplicate_run_is_blocked(self):
        app.state["status"] = "running"
        with patch.dict(os.environ, {"GROQ_API_KEY": "fixture"}, clear=True):
            self.assertEqual(self.client.post("/api/run", json={}).status_code, 409)
    def test_rapid_repeat_is_blocked(self):
        app.last_started = app.time.monotonic()
        with patch.dict(os.environ, {"GROQ_API_KEY": "fixture"}, clear=True):
            self.assertEqual(self.client.post("/api/run", json={}).status_code, 429)
    def test_cancel_keeps_saved_demo_accessible(self):
        app.state["status"] = "running"
        self.assertEqual(self.client.post("/api/cancel").json()["status"], "cancelling")
        self.assertTrue(app.cancel_event.is_set())
        self.assertTrue(self.client.get("/api/demo").json()["briefing"])
    def test_worker_cancel_does_not_fallback(self):
        with patch.object(app, "run", side_effect=InterruptedError()):
            app._worker({})
        self.assertEqual(app.state["status"], "cancelled")
        self.assertIsNone(app.state["error"])
    def test_corrupt_latest_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "latest.json"
            with patch.object(app, "LATEST", target):
                for value in ('{"id":[]}', '[]', 'broken', '{"id":"bad","stories":[7]}'):
                    target.write_text(value)
                    self.assertIsNone(app._load_latest())
    def test_invalid_utf8_latest_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "latest.json"
            target.write_bytes(bytes([255, 254, 253]))
            with patch.object(app, "LATEST", target):
                self.assertIsNone(app._load_latest())
    def test_bad_history_data_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "latest.json").write_text('{"id":[],"generated_at":8}')
            with patch.object(memory, "ROOT", root), patch.object(memory, "ARCHIVE", root / "history"):
                self.assertEqual(memory.history(), [])
    def test_invalid_pin_does_not_overwrite_demo(self):
        self.assertEqual(self.client.post("/api/demo", json={"briefing_id": "does-not-exist"}).status_code, 400)
    def test_unconfigured_teams_does_not_send(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(app.requests, "post") as send:
            self.assertEqual(self.client.post("/api/send-teams").status_code, 400)
            send.assert_not_called()
    def test_teams_timeout_is_safe(self):
        with patch.dict(os.environ, {"TEAMS_WEBHOOK_URL": "https://example.com/SECRET"}, clear=True), patch.object(app, "_load_latest", side_effect=app._demo_briefing), patch.object(app.requests, "post", side_effect=app.requests.Timeout("SECRET")):
            response = self.client.post("/api/send-teams")
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("SECRET", response.text)
    def test_input_bounds(self):
        for value in ({"max_updates": 0}, {"context": "x" * 1001}, {"query": "x" * 201}, {"topics": ["x"] * 13}, {"depth": "bad"}):
            self.assertEqual(self.client.post("/api/run", json=value).status_code, 422)

class EvidenceAndSourcesTests(unittest.TestCase):
    def test_missing_evidence_flag_is_not_supported(self):
        self.assertFalse(WrittenStory(index=0, summary="claim", deck="claim").supported)
    def test_invalid_indices_never_invent_source_zero(self):
        fields = dict(event_key="test", reason="test", significance="major", category="model", impact=5, novelty=5, evidence=5, ecosystem=5, relevance=5)
        with self.assertRaises(ValidationError):
            Event(indices="garbage", **fields)
    def test_source_failure_does_not_stop_other_sources(self):
        def bad():
            raise TimeoutError("SECRET")
        records, errors, coverage = sources._jobs([("bad", "news", bad), ("good", "news", lambda: [{"title":"ok"}])])
        self.assertEqual(len(records), 1)
        self.assertEqual(len(coverage), 2)
        self.assertNotIn("SECRET", repr(errors))
    def test_source_cancellation_propagates(self):
        def log(*args):
            raise InterruptedError()
        with self.assertRaises(InterruptedError):
            sources._jobs([("one", "news", lambda: [])], log)
    def test_papers_and_private_hosts_rejected(self):
        for url in ("https://arxiv.org/abs/123", "https://127.0.0.1/news", "http://example.com/news", "https://host.local/news", "https://example.com/paper.pdf"):
            with self.assertRaises(ValueError):
                sources._safe_url(url)
    def test_read_size_limit(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.headers = {}
        response.iter_content.return_value = [b"x" * 20]
        with patch.object(sources, "_safe_url"), patch.object(sources.requests, "get", return_value=response), patch.object(sources, "MAX_BYTES", 10):
            with self.assertRaises(ValueError):
                sources._get("https://example.com/news")

class LifecycleTests(unittest.TestCase):
    def test_run_api_generates_archives_and_reloads_requested_count(self):
        import time
        from test_briefing import Harness, item
        h = Harness([item(i) for i in range(20)])
        old_state, old_started = dict(app.state), app.last_started
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                app.state.update(status="idle", activity=[], error=None)
                app.last_started = 0
                app.cancel_event.clear()
                with patch.object(app, "LATEST", root / "latest.json"), patch.object(memory, "ROOT", root), patch.object(memory, "ARCHIVE", root / "history"), patch.object(app, "run", side_effect=lambda prefs, log: h.run(prefs["max_updates"])), patch.dict(os.environ, {"GROQ_API_KEY": "fixture"}, clear=True):
                    client = TestClient(app.app)
                    self.assertEqual(client.post("/api/run", json={"max_updates":15}).status_code, 200)
                    deadline = time.monotonic() + 3
                    while app.state["status"] == "running" and time.monotonic() < deadline:
                        time.sleep(.01)
                    response = client.get("/api/state").json()
                    self.assertEqual(response["status"], "complete")
                    self.assertEqual(len(response["briefing"]["stories"]), 15)
                    self.assertTrue(response["briefing"]["target_met"])
                    self.assertEqual(len(client.get("/api/history").json()["briefings"]), 1)
                    self.assertTrue((root / "latest.json").exists())
        finally:
            app.state.clear(); app.state.update(old_state)
            app.last_started = old_started
            app.cancel_event.clear()
    def test_write_failure_preserves_previous_file(self):
        old_state = dict(app.state)
        app.cancel_event.clear()
        try:
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "latest.json"
                target.write_text(json.dumps(app._demo_briefing()), encoding="utf-8")
                original = target.read_bytes()
                with patch.object(app, "LATEST", target), patch.object(app, "run", return_value=app._demo_briefing()), patch.object(app, "remember", side_effect=OSError("SECRET")):
                    app._worker({})
                    self.assertEqual(target.read_bytes(), original)
                    self.assertEqual(app.state["status"], "fallback")
                    self.assertNotIn("SECRET", app.state["error"])
        finally:
            app.state.clear(); app.state.update(old_state)
    def test_groq_only_launcher_does_not_prompt_for_gemini(self):
        import launch
        socket = MagicMock()
        socket.__enter__.return_value = socket
        socket.connect_ex.return_value = 1
        with patch.dict(os.environ, {"GROQ_API_KEY":"fixture"}, clear=True), patch.object(launch, "load_dotenv"), patch.object(launch.socket, "socket", return_value=socket), patch.object(launch.getpass, "getpass") as prompt, patch("sys.argv", ["launch.py", "--port", "8891"]), patch("uvicorn.run") as serve, patch("builtins.print"):
            launch.main()
            prompt.assert_not_called()
            serve.assert_called_once()
    def test_port_collision_reuses_existing_app(self):
        import launch
        socket = MagicMock()
        socket.__enter__.return_value = socket
        socket.connect_ex.return_value = 0
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"app":"signal-and-sense"}'
        with patch.object(launch.socket, "socket", return_value=socket), patch.object(launch.urllib.request, "urlopen", return_value=response), patch("sys.argv", ["launch.py", "--demo"]), patch("uvicorn.run") as serve, patch("builtins.print"):
            launch.main()
            serve.assert_not_called()

class RoutedBriefingIntegrationTests(unittest.TestCase):
    """Run the real agent/router/worker while replacing only external I/O."""
    def setUp(self):
        import agent
        from test_briefing import Harness, item
        self.agent = agent
        self.harness = Harness([item(i) for i in range(20)])
        self.original_build = agent.build_briefing
        self.old_state = dict(app.state)
        app.state.update(status="idle", activity=[], error=None)
        app.cancel_event.clear()
        providers._COOLDOWNS.clear()
        self.instances = []
    def tearDown(self):
        app.state.clear(); app.state.update(self.old_state)
        app.cancel_event.clear()
        providers._COOLDOWNS.clear()
    def factory(self, name, failure):
        harness, instances = self.harness, self.instances
        class FixtureProvider(providers.Provider):
            def __init__(self):
                super().__init__(name, "offline-fixture", 0)
                self.calls = 0
                self.closed = False
                instances.append(self)
            def call(self, prompt, schema, log):
                self.calls += 1
                if failure(schema, self.calls):
                    raise RemoteError(429)
                return harness.ask(prompt, schema)
            def close(self):
                self.closed = True
        return FixtureProvider
    def build(self, prefs, log, ask):
        h = self.harness
        return self.original_build(prefs, log, ask, discover=h.discover, search=h.search, reader=h.read)
    def execute(self, gemini_failure, groq_failure):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            saved = app._demo_briefing()
            (root / "latest.json").write_text(json.dumps(saved), encoding="utf-8")
            stack.enter_context(patch.dict(os.environ, {"GEMINI_API_KEY":"fixture", "GROQ_API_KEY":"fixture"}, clear=True))
            stack.enter_context(patch.dict(providers._PROVIDER_KEYS, {
                "gemini": ("GEMINI_API_KEY", self.factory("Gemini", gemini_failure)),
                "groq": ("GROQ_API_KEY", self.factory("Groq", groq_failure)),
            }, clear=True))
            stack.enter_context(patch.object(self.agent, "build_briefing", side_effect=self.build))
            stack.enter_context(patch.object(app, "LATEST", root / "latest.json"))
            stack.enter_context(patch.object(memory, "ROOT", root))
            stack.enter_context(patch.object(memory, "ARCHIVE", root / "history"))
            stack.enter_context(patch.object(app, "_demo_briefing", return_value=saved))
            app._worker({"max_updates":15})
            result = app.get_state()
            persisted = json.loads((root / "latest.json").read_text(encoding="utf-8"))
            self.assertTrue(all(instance.closed for instance in self.instances))
            return result, persisted, saved
    def test_review_quota_fallback_completes_and_persists_15(self):
        result, persisted, _ = self.execute(lambda schema, count: False, lambda schema, count: True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(persisted["stories"]), 15)
        self.assertTrue(persisted["target_met"])
        self.assertEqual(persisted["provider_attempts"], persisted["model_calls"] + 1)
        self.assertEqual(next(p for p in self.instances if p.name == "Groq").calls, 1)
    def test_writing_quota_fallback_completes_and_persists_15(self):
        result, persisted, _ = self.execute(lambda schema, count: True, lambda schema, count: False)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(persisted["stories"]), 15)
        self.assertEqual(persisted["providers_used"], ["Groq"])
        self.assertEqual(next(p for p in self.instances if p.name == "Gemini").calls, 1)
    def test_mid_run_quota_preserves_supported_partial(self):
        from agent import WrittenBrief
        result, persisted, _ = self.execute(lambda schema, count: count > 1, lambda schema, count: schema is WrittenBrief)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(persisted["stories"]), 5)
        self.assertFalse(persisted["target_met"])
        self.assertTrue(persisted["shortfall_reason"])
        self.assertFalse(result["saved_demo"])
    def test_all_provider_quota_preserves_latest_and_opens_demo(self):
        result, persisted, saved = self.execute(lambda schema, count: True, lambda schema, count: True)
        self.assertEqual(result["status"], "fallback")
        self.assertTrue(result["saved_demo"])
        self.assertEqual(persisted, saved)
        self.assertEqual(result["briefing"]["id"], saved["id"])
        self.assertNotIn("SECRET", json.dumps(result))

class SDKConfigurationTests(unittest.TestCase):
    def test_groq_timeout_and_retries_are_explicit(self):
        with patch("groq.Groq") as client:
            providers.GroqProvider()
            self.assertEqual(client.call_args.kwargs["timeout"], 45)
            self.assertEqual(client.call_args.kwargs["max_retries"], 0)
    def test_openrouter_timeout_and_retries_are_explicit(self):
        with patch("openai.OpenAI") as client:
            providers.OpenRouterProvider()
            self.assertEqual(client.call_args.kwargs["timeout"], 45)
            self.assertEqual(client.call_args.kwargs["max_retries"], 0)
    def test_gemini_timeout_and_retries_are_explicit(self):
        with patch("google.genai.Client") as client:
            providers.GeminiProvider()
            options = client.call_args.kwargs["http_options"]
            self.assertEqual(options.timeout, 45000)
            self.assertEqual(options.retry_options.attempts, 1)
    def test_mistral_timeout_and_retries_are_explicit(self):
        from mistralai.client import Mistral
        with patch.object(Mistral, "__init__", return_value=None) as init:
            providers.MistralProvider()
            self.assertEqual(init.call_args.kwargs["timeout_ms"], 45000)
            self.assertIsNone(init.call_args.kwargs["retry_config"])

if __name__ == "__main__":
    unittest.main()