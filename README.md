# Signal & Sense

A local, general-audience AI news briefing. It searches the full past seven days,
groups coverage into events, ranks developments, reads source evidence, and writes
a newsletter. It does not search research-paper repositories.

## Start

From this folder, with the existing virtual environment:

~~~powershell
.\Start.ps1
~~~

Open http://127.0.0.1:8765. Stop the previous server with Ctrl+C after code changes,
then restart and hard-refresh the browser. The launcher detects an occupied port.
Use another port if needed:

~~~powershell
.\Start.ps1 -Port 8877
~~~

For a presentation using an actual saved briefing, without a new model call:

~~~powershell
.\Start.ps1 -Demo
~~~

Open the address printed by the launcher, including /?demo=1.

For a fresh installation:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

Copy .env.example to .env only if .env does not already exist. Set GEMINI_API_KEY
locally. Never share the file. Existing Windows environment values take precedence
over .env. The launcher accepts a hidden session-only key, or Enter to browse saved
briefings without a key.

## News discovery

Sources include OpenAI, Anthropic, Google and Hugging Face announcements; TechCrunch,
The Verge, VentureBeat and Ars Technica; Simon Willison, Latent Space and
Interconnects; broad Bing News RSS searches; and Hacker News searches.

Watch topics are split on commas/semicolons and sent directly into searches.
This week in AI preserves broad headlines; Explore a topic focuses editorial
selection on the watch query. Interests and project context shape relevance and
explanations. Use non-confidential context: it is sent to the model.

All runs cover seven days, regardless of earlier briefings. Discovery dates are
distinguished from publication dates; a newly discussed page is not automatically
a new release. Paper repositories and PDF links are excluded. Source failures are
visible and do not masquerade as zero news.

## Target count and recovery

Choose 10, 15, or 25 updates as a target. The editor reviews up to 120 new candidates
per round and keeps noteworthy reserves. It tries alternate coverage when an
article is unavailable, replaces unsupported/omitted stories, and can run up to two
follow-up search rounds. Up to five highest-priority stories lead the issue; the
rest are shorter updates.

The target is reached when enough eligible events pass source review.
It is not guaranteed when evidence, discovery, quota or the run budget is
insufficient. A partial briefing states the count and reason. Nothing is invented
or duplicated to fill the count. Empty or failed runs preserve the previous
briefing; non-empty partial results are saved with their shortfall clearly marked.

Budgets: 18 actual model requests including fallback attempts; up to 3 * target + 15
source reads; at most two follow-up rounds; a 15-minute checkpoint between processing
batches. An in-flight network request may finish after that checkpoint. Individual
model requests have a 60-second configured timeout and automatic SDK retries are
disabled. Source HTTP reads have connect/read timeouts and a size limit.

Cancel run stops after the current blocking operation finishes. It may take up to a
request timeout, and does not cancel a request already received by the model provider.

## Explainable ranking

The displayed score is an editorial priority score, not a truth probability:

| Signal | Maximum contribution |
|---|---:|
| Industry impact | 25 |
| Novelty | 20 |
| Cross-site attention | 20 |
| Evidence quality | 15 |
| Ecosystem reach | 10 |
| Reader relevance | 5 |
| Recency | 5 |

The model supplies 0-5 judgments for impact, novelty, provisional evidence quality,
ecosystem reach and relevance. Code combines them with observed coverage and dates.
A recognized major player raises only the ecosystem component; a consequential
newcomer can outrank a minor update from a large company.

Attention uses event coverage across source groups (80% of that component), plus
distinctive entity/keyword frequency across the discovery corpus (20%). Counts
saturate to avoid letting popularity overwhelm significance. Repeated URLs count
once; known parent domains are grouped; matching headlines and very similar
excerpts trigger heuristic copy discounts. Shared blogging platforms count tenants
separately where possible.

These are bounded discovery observations, not measurements of the whole internet
or proof of independent reporting. Grouping, copy detection and event clustering
can be imperfect. A live 15-card run exposed repeated event coverage and a mismatched
source. A reviewed nine-story presentation snapshot is pinned in data/demo.json;
the unedited original is preserved in latest.json and history. Current live runs
may still require editorial review before sharing. Editorial evidence scores precede full-page reading; only
supported stories are published, but the score is not an independent fact check.

## Reading, presentation and history

- Cards show priority, observed source groups and expandable score contributions.
- Search and category filters operate locally within the displayed briefing.
- Export brief downloads Markdown; Print / PDF uses the browser's print dialog.
- The saved-briefing picker opens earlier results without model requests.
- Use for presentation pins the currently displayed briefing to data/demo.json.
- Present saved briefing opens a clearly labeled saved view with recorded activity.
- If no briefing was explicitly pinned, the saved view chooses the archive with the
  most stories (newest on a tie). Pin the result you actually want before presenting.
- Saved mode continues to work without the AI/news APIs. The local server must still
  be running. External source links and hosted fonts may need an internet connection;
  system fonts are available as a fallback.

Latest result: data/latest.json. Archive: data/history/. Presentation snapshot:
data/demo.json, with a sanitized bundled copy at demo/briefing.json for fresh clones. These are local and Git-ignored. Existing archives are never
rewritten to add new scores. Earlier briefings may lack ranking/category metadata.

The audit panel reports candidate outcomes. Discovery results, unique source
candidates and distinct published events are different units; multiple candidates
can represent one published event. Missing model decisions are labeled explicitly.

## API use

The code default is gemini-3.1-flash-lite. GEMINI_MODEL in the current environment
overrides it. GEMINI_FALLBACK_MODEL defaults to the same Lite model. A 429 or
transient server error can trigger one fallback attempt when it differs from the
current model. Requests are spaced by at least 13 seconds within a server process.
This reduces bursts; it does not guarantee remaining daily/token quota.

Typically a 15-story briefing needs one editorial review and three writer calls,
plus any follow-up, omission recovery or fallback. The UI reports the actual model
call count. More stories/search rounds use more quota; no fixed free-tier allowance
or price is assumed. Groq and local Laya integration are deferred.

## Optional Teams

TEAMS_WEBHOOK_URL can point to a Teams Workflows incoming webhook. Sharing happens
only when the Share latest to Teams button is clicked. It always shares the latest
saved briefing, even if another archive is currently displayed. The demo verification
does not send Teams messages.

## Verification

Offline checks use synthetic sources and model outputs and make no external calls:

~~~powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
node --check static/app.js
~~~

See DEMO_GUIDE.md for the reviewed presentation snapshot, walkthrough and recovery steps.
This remains a local prototype: no scheduled delivery, authentication, or guarantee
of exhaustive news coverage. Model judgments and extracted dates can be wrong.
