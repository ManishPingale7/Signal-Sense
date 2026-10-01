# Demo reliability verification

Verified on 1 October 2026 in the existing Windows Python 3.11 environment.

## Results

- **62 offline tests passed** (`unittest discover -s tests -q`).
- **12 browser checks passed** in an isolated headless Chrome instance, including
  desktop and 390px mobile layouts.
- **One live connectivity request passed through Groq on its first attempt**.
  This was a small structured-output request, not a full live news briefing.
- All four installed SDK clients initialized using dummy keys without network calls.
- `pip check` reported no broken dependencies; `node --check static/app.js` passed.
- No Teams messages were sent. No stored API keys were printed or modified.

## Failure matrix

| Scenario | Verified behaviour |
|---|---|
| Provider 429 / quota exhausted | Switch provider; skip exhausted provider for the rest of the run; preserve cooldown across runs in the same server process |
| Timeout, rejected credentials, invalid response | Switch to the next configured provider; avoid retry loops |
| Only Mistral configured | Both review and writing routes work with the offline provider fixture |
| All providers fail | Show the pinned/bundled dated presentation automatically; keep latest saved file intact |
| Request budget exhausted | Stop further attempts; retain supported partial results when present |
| Cancellation | Propagates through provider routing, pacing and source collection; keeps saved results |
| Source unavailable | Continue with other sources; show failure in coverage |
| Old or unreadable source | Reject/replace it; explain a remaining shortfall |
| Unsupported or omitted model output | Replace or retry missing stories once; never invent a source index |
| Invalid inputs, duplicate run, rapid repeat | Return controlled 422, 409 or 429 responses |
| Corrupt JSON, wrong saved shape, invalid UTF-8 | Ignore invalid saved file and retain access to valid demo data |
| Persistence failure | Previous latest file is unchanged; saved presentation remains available |
| Real agent/router/worker with simulated quota failures | Review and writing fallback each produce and persist 15 updates; mid-run exhaustion saves five supported stories with an explicit shortfall; exhaustion before any result preserves latest and opens the demo |
| Full API run with offline fixtures | Generates 15 ranked updates, archives them, reloads them through state/history APIs |
| Connection lost after page load | Existing cards remain visible and usable |
| Teams unavailable | Controlled error; tested with mocked requests only |

Browser checks also covered saved-date labels, story search/reset, category filters,
HTTPS source links, expandable explanations, saved mode during a live run, automatic
fallback, Markdown export and PDF generation. The saved presentation contains the
same nine reviewed stories dated 27 September 2026.

## Limits

Provider quota and uptime cannot be guaranteed. Pacing reduces request bursts but
cannot prevent daily/token limits or limits from other applications using the same
account. Cooldowns are in-memory and reset when the server restarts.

The 45-second SDK timeout is a configured network timeout, not a guarantee that an
entire briefing finishes in 45 seconds. Discovery and writing require multiple
operations. Cancellation can wait for the current blocking request to finish.

These tests exercise recovery and app flows. They do not establish that every live
news claim is correct, that every important headline will be found, or that all four
providers are currently reachable. Only Groq connectivity was checked live during
this verification. Lead the meeting with the saved presentation; live generation
is optional.

## Repeat the checks

From the project folder:

~~~powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
node --check static/app.js
.\.venv\Scripts\python.exe -B -m pip check
~~~

`tests/browser_smoke.py` additionally needs a local app on port 8890 and an isolated
Chrome instance with remote debugging on port 9224. It uses the installed `websockets`
package and simulates failed live states at the browser fetch boundary. It does not
call the live generation or Teams endpoints. Browser ports can be changed with
`--port` and `--chrome-port`. It writes Markdown/PDF checks under ignored `data/`.