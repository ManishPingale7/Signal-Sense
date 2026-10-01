const runButton = document.getElementById("run-button");
const teamsButton = document.getElementById("teams-button");
const topics = document.getElementById("topics");
const depths = document.getElementById("depths");
const activityList = document.getElementById("activity-list");
const briefContent = document.getElementById("brief-content");
const toast = document.getElementById("toast");
let lastBriefId = null;
let currentBrief = null;
let demoMode = new URLSearchParams(location.search).get("demo") === "1";
let refreshing = false;
const demoButton = document.getElementById("demo-button");
const cancelButton = document.getElementById("cancel-button");
const pinButton = document.getElementById("pin-button");
const searchStories = document.getElementById("story-search");
const categoryFilter = document.getElementById("story-category");

let latestHistoryId = null;
let historyBriefs = [];
const historyPicker = document.getElementById("brief-history");
historyPicker.addEventListener("change", () => {
  const brief = historyPicker.value ? historyBriefs.find(item => item.id === historyPicker.value) : historyBriefs[0];
  if (brief) renderBrief(brief);
});
async function refreshHistory(latest) {
  if (!latest || latestHistoryId === latest.id) return;
  const response = await fetch("/api/history", {cache: "no-store", signal: AbortSignal.timeout(8000)});
  if (!response.ok) return;
  const payload = await response.json();
  historyBriefs = payload.briefings || [];
  const selected = historyPicker.value;
  historyPicker.replaceChildren(el("option", "", "Latest briefing"));
  historyPicker.firstElementChild.value = "";
  historyBriefs.forEach(brief => {
    const label = new Date(brief.generated_at).toLocaleString("en-IN", {day:"numeric", month:"short", hour:"2-digit", minute:"2-digit"});
    const option = el("option", "", label + " · " + brief.stories.length + " stories");
    option.value = brief.id;
    historyPicker.appendChild(option);
  });
  historyPicker.value = selected;
  latestHistoryId = latest.id;
}
let lastActivitySignature = "";
let toastTimer;
const modes = document.getElementById("modes");
const projectContext = document.getElementById("project-context");
const exploreQuery = document.getElementById("explore-query");
const maxUpdates = document.getElementById("max-updates");
maxUpdates.addEventListener("change", savePrefs);
function selectedMode() { return modes.querySelector(".active")?.dataset.mode || "weekly"; }
function syncMode() {
  document.getElementById("query-group").hidden = false;
  exploreQuery.placeholder = selectedMode() === "explore" ? "e.g. zero-shot classifiers, open decision models" : "e.g. open-weight models, zero-shot classifiers, frontier benchmarks";
}
modes.addEventListener("click", event => {
  const button = event.target.closest("[data-mode]");
  if (!button) return;
  modes.querySelectorAll("button").forEach(item => {
    item.classList.toggle("active", item === button);
    item.setAttribute("aria-pressed", String(item === button));
  });
  syncMode(); savePrefs();
});
projectContext.addEventListener("input", savePrefs);
exploreQuery.addEventListener("input", savePrefs);

document.getElementById("today").textContent = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit", month: "short", year: "numeric"
}).format(new Date()).toUpperCase();

function message(text) {
  toast.textContent = text;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 4500);
}

function selectedTopics() {
  return Array.from(topics.querySelectorAll(".topic.active")).map(button => button.dataset.topic);
}

function selectedDepth() {
  return depths.querySelector("button.active")?.dataset.depth || "explain";
}

function savePrefs() {
  try { localStorage.setItem("signal-sense-prefs", JSON.stringify({
    topics: selectedTopics(), depth: selectedDepth(), mode: selectedMode(),
    context: projectContext.value, query: exploreQuery.value, max_updates: Number(maxUpdates.value)
  })); } catch (_) { /* Preferences can still be used when storage is unavailable. */ }
}

try {
  const saved = JSON.parse(localStorage.getItem("signal-sense-prefs") || "{}");
  projectContext.value = saved.context || "";
  exploreQuery.value = saved.query || "";
  maxUpdates.value = [10, 15, 25].includes(Number(saved.max_updates)) ? String(saved.max_updates) : "15";
  modes.querySelectorAll("button").forEach(item => {
    const active = item.dataset.mode === (saved.mode === "explore" ? "explore" : "weekly");
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", String(active));
  });
  syncMode();
  const availableTopics = Array.from(topics.querySelectorAll(".topic")).map(button => button.dataset.topic);
  const restoredTopics = Array.isArray(saved.topics) ? saved.topics.filter(topic => availableTopics.includes(topic)) : [];
  if (restoredTopics.length) {
    topics.querySelectorAll(".topic").forEach(button => {
      const active = restoredTopics.includes(button.dataset.topic);
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }
  if (saved.depth) {
    depths.querySelectorAll("button").forEach(button => {
      button.classList.toggle("active", button.dataset.depth === saved.depth);
      button.setAttribute("aria-pressed", String(button.dataset.depth === saved.depth));
    });
  }
} catch (_) {}

topics.addEventListener("click", event => {
  const button = event.target.closest(".topic");
  if (!button) return;
  if (button.classList.contains("active") && selectedTopics().length === 1) {
    message("Keep at least one interest selected.");
    return;
  }
  button.classList.toggle("active");
  button.setAttribute("aria-pressed", String(button.classList.contains("active")));
  savePrefs();
});

depths.addEventListener("click", event => {
  const button = event.target.closest("button[data-depth]");
  if (!button) return;
  depths.querySelectorAll("button").forEach(item => {
    item.classList.toggle("active", item === button);
    item.setAttribute("aria-pressed", String(item === button));
  });
  savePrefs();
});

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {}),
    signal: AbortSignal.timeout(15000)
  });
  let payload;
  try { payload = await response.json(); } catch (_) { payload = {}; }
  if (!response.ok) throw new Error(payload.detail || "The request failed.");
  return payload;
}

runButton.addEventListener("click", async () => {
  if (demoMode) return;
  try {
    runButton.disabled = true;
    await post("/api/run", {topics: selectedTopics(), depth: selectedDepth(),
      mode: selectedMode(), context: projectContext.value, query: exploreQuery.value, max_updates: Number(maxUpdates.value)});
    historyPicker.value = "";
    message("The news desk is preparing your briefing.");
    await refresh();
  } catch (error) {
    runButton.disabled = false;
    message(error.message);
  }
});

teamsButton.addEventListener("click", async () => {
  try {
    teamsButton.disabled = true;
    await post("/api/send-teams", {});
    message("Briefing sent to Microsoft Teams.");
  } catch (error) {
    message(error.message);
  } finally {
    teamsButton.disabled = false;
  }
});

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderActivity(entries) {
  const signature = JSON.stringify(entries);
  if (signature === lastActivitySignature) return;
  lastActivitySignature = signature;
  activityList.replaceChildren();
  if (!entries.length) {
    activityList.appendChild(el("div", "activity-empty", "The desk is quiet for now. Start a briefing to watch it work."));
    return;
  }
  const icons = {collect: "◉", decide: "↗", inspect: "⌕", write: "✎", verify: "✓", saved: "✓", warning: "!", error: "!", share: "↗"};
  entries.forEach(entry => {
    const row = el("div", "activity-entry " + entry.kind);
    row.appendChild(el("div", "activity-icon", icons[entry.kind] || "·"));
    const content = el("div");
    content.appendChild(el("div", "activity-entry-title", entry.title));
    content.appendChild(el("p", "activity-entry-detail", entry.detail));
    content.appendChild(el("div", "activity-entry-time", entry.at));
    row.appendChild(content);
    activityList.appendChild(row);
  });
  activityList.scrollTop = activityList.scrollHeight;
}

function renderProgress(data) {
  const entries = data.activity || [];
  const ranks = {collect: 0, decide: 1, inspect: 2, write: 3, verify: 4, saved: 4};
  const stage = entries.reduce((current, entry) => ranks[entry.kind] ?? current, -1);
  const complete = data.status === "complete";
  document.querySelectorAll(".workflow li").forEach((item, index) => {
    const done = complete || index < stage;
    const active = !complete && index === stage;
    item.classList.toggle("done", done);
    item.classList.toggle("active", active && data.status === "running");
    item.classList.toggle("failed", active && data.status === "error");
    item.querySelector(".step-number").textContent = done ? "✓" : String(index + 1);
    if (active) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });
  const latest = entries[entries.length - 1];
  let description = "Ready when you are. Choose your interests and generate a brief.";
  if (data.status === "error") description = data.error || "The agent stopped. Open activity for details.";
  else if (data.status === "cancelled") description = "Run cancelled. Your saved briefings remain available.";
  else if (data.status === "cancelling") description = "Cancelling after the current request finishes. Your saved briefing is safe.";
  else if (complete) description = data.briefing?.shortfall_reason || "Your briefing is ready. Explore the stories and original sources below.";
  else if (latest) description = latest.title + (latest.detail ? " — " + latest.detail : "");
  else if (data.briefing) description = "Showing your saved briefing. Generate a new one whenever you’re ready.";
  if (data.status === "running" && data.started_at) {
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(data.started_at).getTime()) / 1000));
    description = Math.floor(seconds / 60) + "m " + (seconds % 60) + "s · " + description;
  }
  if (demoMode) description = "Recorded activity from this saved briefing. No new run is started by presentation mode.";
  document.getElementById("activity-title").textContent = demoMode ? "How this briefing was built" : "Your agent at work";
  document.getElementById("activity-current").textContent = description;
  document.getElementById("activity-count").textContent = entries.length + " events";
}

function dateLabel(value) {
  if (!value || Number.isNaN(new Date(value).getTime())) return "date unavailable";
  return new Intl.DateTimeFormat("en-IN", {day: "numeric", month: "short", year: "numeric"}).format(new Date(value));
}

function storyCard(story, index) {
  const isBrief = story.section === "brief";
  const card = el("article", "story-card" + (isBrief ? " short-update" : ""));
  const top = el("div", "story-top");
  const overline = el("div", "story-overline");
  overline.appendChild(el("span", "", story.kind));
  overline.appendChild(el("span", "sep", "/"));
  overline.appendChild(el("span", "", story.source));
  overline.appendChild(el("span", "sep", "/"));
  overline.appendChild(el("span", "", (story.date_basis === "published" ? "Published " : story.kind === "News" ? "Discovered " : "") + dateLabel(story.published)));
  top.appendChild(overline);
  top.appendChild(el("span", "story-number", String(index + 1).padStart(2, "0")));
  card.appendChild(top);
  if (story.ranking) {
    const badges = el("div", "ranking-badges");
    badges.appendChild(el("span", "priority-badge", story.ranking.label + " · " + story.ranking.score + "/100"));
    const count = story.ranking.coverage?.source_count || 0;
    badges.appendChild(el("span", "coverage-badge", count + (count === 1 ? " source group" : " source groups") + " observed"));
    card.appendChild(badges);
  }
  card.appendChild(el("h3", "", story.title));
  card.appendChild(el("p", "story-deck", isBrief ? story.summary : story.deck));
  if (!isBrief) card.appendChild(el("p", "lead-summary", story.summary));
  const detail = el("div", "story-detail");
  const why = el("div", "why-box");
  why.appendChild(el("span", "", "WHY IT MATTERS ↗"));
  why.appendChild(el("p", "", story.why_it_matters));
  detail.appendChild(why);
  for (const [label, value] of [["What's new", story.novelty], ["Evidence & limitations", story.evidence], ["Try next", story.next_step]]) {
    if (!value) continue;
    const section = el("div", "insight-block");
    section.appendChild(el("h4", "", label));
    section.appendChild(el("p", "", value));
    detail.appendChild(section);
  }
  const expanded = el("details", "story-expanded");
  expanded.appendChild(el("summary", "", "Why it matters & source evidence"));
  expanded.appendChild(detail);
  if (story.related_sources?.length) {
    const related = el("div", "related-coverage");
    related.appendChild(el("h4", "", "More coverage"));
    story.related_sources.forEach(source => {
      if (!/^https:\/\//i.test(source.url || "")) return;
      const link = el("a", "", source.source + " ↗");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      related.appendChild(link);
    });
    detail.appendChild(related);
  }
  if (story.ranking) detail.appendChild(rankingDetails(story.ranking));
  card.appendChild(expanded);
  const bottom = el("div", "story-bottom");
  bottom.appendChild(el("span", "story-selection", "SELECTED BECAUSE · " + story.selection_reason));
  const link = el("a", "story-link", "READ ORIGINAL ↗");
  link.href = /^https:\/\//i.test(story.url || "") ? story.url : "#";
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  bottom.appendChild(link);
  card.appendChild(bottom);
  return card;
}

function selectionBreakdown(audit) {
  const panel = el("details", "selection-breakdown");
  panel.appendChild(el("summary", "", "How this briefing was selected"));
  const counts = audit.counts || {};
  panel.appendChild(el("p", "selection-funnel",
    (counts.discovered ?? 0) + " results -> " + (counts.unique_candidates ?? 0) + " unique -> " +
    (counts.shortlisted ?? 0) + " shortlisted -> " + (counts.selected ?? 0) + " selected -> " +
    (counts.evidence_ready ?? 0) + " with evidence -> " + (counts.published ?? 0) + " published"));
  panel.appendChild(el("p", "audit-help",
    "Search discovered candidates to see their final outcome. Duplicate headlines may be grouped under another title. A missing title does not prove it was never covered elsewhere."));
  const label = el("label", "field-label", "Find a discovered story");
  const search = el("input", "audit-search");
  search.type = "search";
  search.placeholder = "Search a model, topic, or headline";
  label.appendChild(search);
  panel.appendChild(label);
  const total = el("p", "audit-total");
  total.setAttribute("aria-live", "polite");
  panel.appendChild(total);
  const list = el("div", "audit-candidates");
  panel.appendChild(list);
  const labels = {
    not_shortlisted: "Outside shortlist", editorial_unreported: "No explicit model decision",
    editorial_rejected: "Not selected by editor", duplicate_event: "Duplicate event",
    capacity: "Briefing size limit", outside_date_window: "Outside seven-day window",
    insufficient_evidence: "Insufficient readable evidence", unsupported_by_source: "Not supported by source",
    writer_omitted: "Omitted by writer", published: "Published", selected: "Selected",
    evidence_ready: "Evidence collected", reserve: "Ranked reserve", writer_error: "Writer unavailable"
  };
  const render = () => {
    const query = search.value.trim().toLowerCase();
    const candidates = (audit.candidates || []).filter(item =>
      (item.title + " " + item.url + " " + item.reason).toLowerCase().includes(query));
    total.textContent = candidates.length + " matching candidates" + (candidates.length > 100 ? " — showing the first 100; narrow your search to find more" : "");
    list.replaceChildren();
    candidates.slice(0, 100).forEach(item => {
      const row = el("article", "audit-row");
      row.appendChild(el("span", "audit-stage", labels[item.stage] || item.stage));
      row.appendChild(el("h3", "", item.title));
      row.appendChild(el("p", "", item.reason));
      if (/^https:\/\//i.test(item.url || "")) {
        const link = el("a", "", "Open source");
        link.href = item.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        row.appendChild(link);
      }
      list.appendChild(row);
    });
  };
  search.addEventListener("input", render);
  panel.addEventListener("toggle", () => { if (panel.open) render(); });
  return panel;
}

function renderBrief(briefing) {
  if (!briefing || briefing.id === lastBriefId) return;
  currentBrief = briefing;
  document.getElementById("export-button").disabled = false;
  document.getElementById("print-button").disabled = false;
  pinButton.disabled = demoMode;
  lastBriefId = briefing.id;
  briefContent.replaceChildren();
  const lead = el("div", "brief-lead");
  lead.appendChild(el("span", "brief-date", "ISSUE " + briefing.id.slice(0, 8) + " / SAVED RUN"));
  lead.appendChild(el("p", "", briefing.opening));
  if (briefing.shortfall_reason) lead.appendChild(el("p", "shortfall-note", briefing.shortfall_reason));
  const metrics = el("div", "brief-metrics");
  const words = briefing.stories.reduce((n, s) => n + ((s.summary || "") + " " + (s.deck || "")).split(/\s+/).length, 0);
  const values = [
    [briefing.stories.length + (briefing.target_updates ? "/" + briefing.target_updates : ""), "updates ready"],
    [String(briefing.discovery_results ?? briefing.selection_audit?.counts?.discovered ?? "—"), "discovery results"],
    [String(briefing.model_calls ?? "—"), "model calls"],
    ["~" + Math.max(1, Math.ceil(words / 200)) + " min", "estimated read"]
  ];
  values.forEach(([value, label]) => {
    const metric = el("div", "");
    metric.appendChild(el("strong", "", value)); metric.appendChild(el("span", "", label));
    metrics.appendChild(metric);
  });
  lead.appendChild(metrics);
  if (briefing.coverage?.length) {
    const coverage = el("details", "source-coverage");
    const succeeded = briefing.coverage.filter(source => source.status === "ok").length;
    coverage.appendChild(el("summary", "", "Discovery coverage · " + succeeded + "/" + briefing.coverage.length + " source checks reached"));
    const list = el("ul", "");
    briefing.coverage.forEach(source => {
      list.appendChild(el("li", source.status === "ok" ? "" : "source-unavailable",
        source.name + " — " + (source.status === "ok" ? source.recent_results + " recent results" : "Unavailable")));
    });
    coverage.appendChild(list);
    lead.appendChild(coverage);
  }
  briefContent.appendChild(lead);
  if (!briefing.stories.length) {
    const empty = el("div", "empty-state");
    empty.appendChild(el("h3", "", "Nothing new worth forcing."));
    empty.appendChild(el("p", "", "This search found no sufficiently fresh, relevant stories. Your earlier briefings remain saved locally. Explore a topic for a different angle."));
    briefContent.appendChild(empty);
  }
  const search = searchStories.value.trim().toLowerCase();
  const visible = briefing.stories.filter(story =>
    (!categoryFilter.value || story.category === categoryFilter.value) &&
    [story.title, story.deck, story.summary, story.source, ...(story.topics || [])].join(" ").toLowerCase().includes(search));
  document.getElementById("filter-count").textContent = (search || categoryFilter.value)
    ? visible.length + " of " + briefing.stories.length + " updates match" : "";
  if (!visible.length && briefing.stories.length) {
    const empty = el("div", "empty-state");
    empty.appendChild(el("h3", "", "No matching updates"));
    empty.appendChild(el("p", "", "Try a different keyword or choose All updates."));
    briefContent.appendChild(empty);
  }
  const leads = visible.filter(story => story.section !== "brief");
  const briefs = visible.filter(story => story.section === "brief");
  let number = 0;
  for (const [title, description, stories] of [
    ["Lead stories", "The developments shaping this week.", leads],
    ["Also worth knowing", "Emerging models, useful releases, and other updates worth a moment.", briefs]
  ]) {
    if (!stories.length) continue;
    const section = el("section", "newsletter-section");
    const heading = el("div", "newsletter-heading");
    heading.appendChild(el("h2", "", title));
    heading.appendChild(el("p", "", description));
    section.appendChild(heading);
    const grid = el("div", "newsletter-grid");
    stories.forEach(story => grid.appendChild(storyCard(story, number++)));
    section.appendChild(grid);
    briefContent.appendChild(section);
  }
  if (briefing.selection_audit) briefContent.appendChild(selectionBreakdown(briefing.selection_audit));
  document.getElementById("brief-meta").textContent =
    briefing.stories.length + " updates · " + dateLabel(briefing.generated_at);
}


function rankingDetails(ranking) {
  const panel = el("section", "ranking-details");
  panel.appendChild(el("h4", "", "Why this ranks here"));
  const names = {impact: "Industry impact", novelty: "What's new", attention: "Cross-site attention",
    evidence: "Evidence quality", ecosystem: "Ecosystem reach", relevance: "Your interests", freshness: "Recency"};
  for (const [key, weight] of Object.entries(ranking.weights || {})) {
    const row = el("div", "score-row");
    row.appendChild(el("span", "", names[key] || key));
    const meter = el("meter", "");
    meter.min = 0; meter.max = weight; meter.value = ranking.contributions?.[key] || 0;
    meter.setAttribute("aria-label", names[key] || key);
    row.appendChild(meter);
    row.appendChild(el("span", "", meter.value + " / " + weight));
    panel.appendChild(row);
  }
  const frequency = ranking.keyword_frequency || [];
  if (frequency.length) panel.appendChild(el("p", "ranking-note", "Observed keyword coverage: " +
    frequency.map(f => f.keyword + " · " + f.source_count + " source groups").join("; ")));
  panel.appendChild(el("p", "ranking-note", ranking.method));
  const discount = ranking.coverage?.suspected_copies_discounted || 0;
  if (discount) panel.appendChild(el("p", "ranking-note", discount + " likely copied coverage entries discounted."));
  return panel;
}

function applyDemoMode() {
  document.body.classList.toggle("presentation-mode", demoMode);
  document.getElementById("demo-banner").hidden = !demoMode;
  demoButton.hidden = demoMode;
  document.getElementById("demo-note").textContent = currentBrief
    ? "Actual saved result from " + dateLabel(currentBrief.generated_at) + ". It is not a new live search."
    : "An actual saved result. This view does not start a new search.";
  const url = new URL(location.href);
  if (demoMode) url.searchParams.set("demo", "1"); else url.searchParams.delete("demo");
  window.history.replaceState({}, "", url);
}

async function enterDemo() {
  try {
    const response = await fetch("/api/demo", {cache: "no-store", signal: AbortSignal.timeout(8000)});
    if (!response.ok) throw new Error("Could not load the saved demo.");
    const data = await response.json();
    if (!data.briefing) {
      demoMode = false; applyDemoMode();
      message("Generate a briefing first, then save it for presentation.");
      return;
    }
    demoMode = true;
    lastBriefId = null;
    searchStories.value = ""; categoryFilter.value = "";
    renderBrief(data.briefing);
    applyDemoMode();
    renderActivity(data.briefing.activity || []);
    renderProgress({status: "complete", briefing: data.briefing, activity: data.briefing.activity || []});
    document.getElementById("status-label").textContent = "SAVED RUN";
    document.querySelector(".activity-live").className = "activity-live complete";
    pinButton.disabled = true;
    runButton.disabled = true; teamsButton.disabled = true;
  } catch (error) { demoMode = false; applyDemoMode(); message(error.message); }
}

demoButton.addEventListener("click", enterDemo);
document.getElementById("exit-demo").addEventListener("click", () => {
  demoMode = false; lastBriefId = null; historyPicker.value = "";
  applyDemoMode(); refresh();
});
cancelButton.addEventListener("click", async () => {
  cancelButton.disabled = true;
  try { await post("/api/cancel"); await refresh(); }
  catch (error) { message(error.message); }
  finally { cancelButton.disabled = false; }
});
pinButton.addEventListener("click", async () => {
  if (!currentBrief) return;
  pinButton.disabled = true;
  try {
    await post("/api/demo", {briefing_id: currentBrief.id});
    message("This briefing is saved for your presentation.");
  } catch (error) { message(error.message); }
  finally { pinButton.disabled = demoMode; }
});
for (const node of [searchStories, categoryFilter]) node.addEventListener("input", () => {
  lastBriefId = null; renderBrief(currentBrief);
});
document.getElementById("export-button").addEventListener("click", () => {
  if (!currentBrief) return;
  const lines = ["# Signal & Sense", "", "Saved: " + dateLabel(currentBrief.generated_at), "",
    currentBrief.opening, "", currentBrief.shortfall_reason || ""];
  currentBrief.stories.forEach((story, i) => {
    lines.push("", "## " + (i + 1) + ". " + story.title, "", story.summary, "",
      "**Why it matters:** " + story.why_it_matters, "", "**Evidence:** " + story.evidence,
      "", "Source: " + story.url);
    if (story.ranking) lines.push("", "Editorial priority: " + story.ranking.score + "/100 (not factual confidence).");
  });
  const url = URL.createObjectURL(new Blob([lines.join("\n")], {type: "text/markdown;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url; link.download = "signal-and-sense-" + currentBrief.id.slice(0, 8) + ".md";
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.getElementById("print-button").addEventListener("click", () => window.print());

async function refresh() {
  if (refreshing || demoMode) return;
  refreshing = true;
  try {
    const response = await fetch("/api/state", {cache: "no-store", signal: AbortSignal.timeout(8000)});
    if (!response.ok) throw new Error("Could not read the agent state.");
    const data = await response.json();
    document.getElementById("connection-banner").hidden = true;
    renderActivity(data.activity || []);
    try { await refreshHistory(data.briefing); } catch (_) { /* Current briefing remains usable. */ }
    if (!historyPicker.value) renderBrief(data.briefing);
    if (data.saved_demo && data.briefing) {
      demoMode = true; lastBriefId = null;
      renderBrief(data.briefing); applyDemoMode();
      renderActivity(data.briefing.activity || []);
      renderProgress({status: "complete", activity: data.briefing.activity || []});
      document.getElementById("status-label").textContent = "SAVED RUN";
      runButton.disabled = true; teamsButton.disabled = true; cancelButton.hidden = true;
      message("Live service unavailable. Showing a dated saved briefing.");
      return;
    }
    const isRunning = ["running", "cancelling"].includes(data.status);
    runButton.disabled = isRunning || !data.configured;
    runButton.firstElementChild.textContent = isRunning ? "Preparing your brief…" : "Generate my brief";
    cancelButton.hidden = !isRunning;
    cancelButton.disabled = data.status === "cancelling";
    demoButton.disabled = false;
    document.getElementById("config-note").hidden = data.configured;
    document.querySelector(".activity-live").className = "activity-live " + data.status;
    document.getElementById("status-label").textContent =
      ({idle: "READY", running: "WORKING", cancelling: "STOPPING", cancelled: "CANCELLED", complete: "DONE", error: "STOPPED"})[data.status] || "READY";
    renderProgress(data);
    teamsButton.disabled = !data.teams_configured || !data.briefing || isRunning;
    document.getElementById("teams-note").textContent = data.teams_configured
      ? "Shares the latest saved briefing to your Teams webhook." : "Teams connection optional for this demo.";
    if (data.status === "error" && data.error && data.error !== refresh.lastError) {
      refresh.lastError = data.error; message(data.error);
    }
  } catch (_) {
    document.getElementById("connection-banner").hidden = false;
    runButton.disabled = true;
  } finally { refreshing = false; }
}
if (demoMode) enterDemo(); else refresh();
setInterval(refresh, 2000);
