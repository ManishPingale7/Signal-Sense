# Signal & Sense: director demo

## The pitch

"Keeping up with AI is a discovery and prioritization problem. Signal & Sense
turns a week of fragmented announcements and discussion into a source-linked,
ranked briefing, with an explanation of why each update matters."

## Before the meeting

1. Open the reviewed snapshot now: http://127.0.0.1:8877/?demo=1
2. Tomorrow, start the server with .\Start.ps1 -Port 8877 -Demo and open the
   address it prints. If another server occupies that port, stop that terminal
   with Ctrl+C and run the command again.
3. The reviewed nine-story snapshot is already pinned. Do not click
   Use for presentation from the raw latest briefing; that would replace it.
4. Check the saved date and a few original source links before speaking.
5. Export brief to keep a Markdown copy. Use Print / PDF for a portable backup.
6. Keep the local server running and the laptop plugged in.
7. Lead with the saved result. A live run is optional and may take several
   minutes or encounter provider limits; the meeting does not depend on it.

Default-port presentation startup: .\Start.ps1 -Demo

## Three-minute walkthrough

### 0:00-0:30 — Problem and result

Show the completed briefing in saved presentation mode.

"This is an actual saved run, clearly labeled with its date. It contains nine
distinct, source-linked updates after review of the live agent output. The agent
found and explained the stories; its first pass also repeated some coverage, which
we removed from the presentation copy."

Point to the update count and discovery count. Do not describe discovery results
as unique events or independent sources.

### 0:30-1:15 — Show editorial judgment

Open a high-priority story and expand Why it matters & source evidence.

"The score combines impact, novelty, evidence, reach and observed cross-site
attention. A big company gets a limited reach advantage; a useful new entrant can
still rank higher. The score expresses priority, not certainty that a claim is true."

Show the original link and evidence limitations. Vendor benchmarks remain vendor
claims unless independent evidence is available.

### 1:15-2:00 — Show the agent's decisions

Open recorded activity and How this briefing was selected.

"The workflow can decide which sources deserve reading and what gaps need another
search. If a source fails or a proposed story is unsupported, it tries an alternate
source or takes a ranked replacement. The selected count is a target, and shortfalls
are explained."

Use the activity from this actual run. If no follow-up was needed, say so; do not
claim a step happened merely because the system supports it.

### 2:00-2:30 — Show usefulness

Search a company/model in the briefing. Filter a category, then restore All updates.
Show export and the saved-briefing picker after leaving presentation mode.

"A team can skim the leads, scan shorter updates, and follow original sources.
It supports personal interests without losing the week's important headlines."

### 2:30-3:00 — Architecture and next step

"Python handles discovery, source reading, ranking arithmetic and persistence.
Gemini makes bounded editorial decisions and writes grounded explanations.
The browser exposes the evidence and activity, so this is inspectable."

"Next I would measure editorial quality with team feedback, add scheduled Teams
delivery, and evaluate a small local classifier such as Laya."

## Architecture

~~~mermaid
flowchart LR
    P[Interests and seven-day window] --> D[Feeds, news search and community]
    D --> M[Merge duplicate coverage]
    M --> E[Model groups and scores events]
    E --> R[Code calculates weighted ranking]
    R --> S[Read original evidence]
    S --> W[Model writes grounded summaries]
    S -->|Unavailable source| A[Alternate source or reserve]
    A --> S
    W -->|Unsupported story| A
    W --> C{Target reached?}
    C -->|No, budget remains| F[Targeted follow-up search]
    F --> D
    C -->|Yes or budget exhausted| B[Saved briefing and decision audit]
    B --> UI[Web view, export, optional Teams]
~~~

The code orchestrates the loop and enforces budgets. The LLM selects events and
proposes searches; the application executes only its allowed operations. This is
a bounded agentic workflow, not an unrestricted autonomous agent.

## Questions the director might ask

**How is this more than asking a chatbot for AI news?**
It retrieves dated sources, groups repeated coverage, reads evidence, retains
reserves, performs bounded follow-up searches, and records outcomes. A free-form
chat answer alone does not provide those explicit controls.

**Why nine updates when the target was 15?**
The live run produced 15 cards, but review found six duplicates, source mismatches
or minor items. This presentation keeps the nine distinct updates we could defend.
The target is a goal, and further event-level deduplication remains a next step.

**Why didn't it find every major launch?**
Coverage depends on reachable/indexed sources and model judgments. The audit makes
the gap inspectable. This prototype does not claim to crawl the entire internet.

**Does repeated coverage prove importance or accuracy?**
No. Coverage is one capped attention signal. Known source families and probable
copies are discounted. Significance and evidence have separate weight.

**What if the API fails?**
The previous saved briefing remains available. Non-empty partial runs say what
stopped them. The presentation view uses an actual saved result without a fresh
API call.

**What does it cost?**
It uses your model provider account and its current quota/pricing. Typical clean
15-story runs need about four model calls; follow-up and recovery add calls. Show
the actual count from the saved briefing. There is no guarantee of free usage.

**Is it production-ready?**
No. It is a working local prototype. Scheduling, access controls, deployment,
editorial evaluation and team delivery operations remain future work.

## Recovery during the meeting

- Rate limit or network failure: choose Present saved briefing.
- Port occupied: use the already-running app, or .\Start.ps1 -Port 8877 -Demo.
- Old UI after a restart: Ctrl+Shift+R.
- Missing new ranking badges: select the newly generated briefing.
- Wrong saved demo: leave presentation mode, choose the right archive and pin it.
- No internet: use the saved view or exported file; source links may not open.
- Stop a long live run: Cancel run. The current request may finish before it stops.
