import { Playback } from "./playback.js";

const $ = (id) => document.getElementById(id);
const ELEMENT = { Heart: "#e8506a", Skill: "#3fbf6a", Body: "#e6b422", Bravery: "#3f8fe8", Wisdom: "#a46be8" };
const STORE = "nbsolver.";

const state = {
  units: [],
  byId: new Map(),
  missions: [],
  roster: emptyRoster(),
  profile: localStorage.getItem(`${STORE}profile`) || "",
  playback: null,
  solving: 0,
};

function emptyRoster() {
  return { player_id: "", team_cost_limit: 200, units: [] };
}

function unitLabel(u) {
  return `${u.name} — ${u.title} (${u.rarity}★) #${u.unit_id}`;
}

function idFromLabel(text) {
  const match = /#(\d+)\s*$/.exec(text || "");
  return match ? Number(match[1]) : null;
}

function dot(element) {
  return `<span class="el" style="background:${ELEMENT[element] || "#888"}"></span>`;
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// ---------- box ----------

function saveRoster() {
  state.roster.player_id = state.profile;
  state.roster.team_cost_limit = Number($("cost-limit").value) || 200;
  localStorage.setItem(`${STORE}profile`, state.profile);
  localStorage.setItem(`${STORE}roster.${state.profile || "default"}`, JSON.stringify(state.roster));
  renderRoster();
}

function loadRoster() {
  const saved = localStorage.getItem(`${STORE}roster.${state.profile || "default"}`);
  state.roster = saved ? JSON.parse(saved) : emptyRoster();
  $("cost-limit").value = state.roster.team_cost_limit || 200;
  renderRoster();
}

function owned(unitId, level, limitBreak = 0) {
  return { unit_id: unitId, level, luck: 0, dupes: 0, limit_break: limitBreak, abilities_unlocked: [], manually_added: true };
}

function maxLevel(unit) {
  return Math.max(unit.max_level || 1, unit.max_level_limit_break || 1);
}

// Mirrors Unit.cost_with_abilities: cost falls toward its floor as abilities unlock.
function costOf(unit, owned) {
  const total = (unit.abilities || []).length;
  const unlocked = Math.min(owned.dupes || 0, total);
  const floor = unit.cost_all_abilities ?? unit.cost;
  if (!total || !unlocked) return unit.cost;
  if (unlocked >= total) return floor;
  return Math.round(unit.cost + (floor - unit.cost) * (unlocked / total));
}

function renderRoster() {
  const body = $("roster").querySelector("tbody");
  const rows = state.roster.units
    .map((o, index) => ({ o, index, u: state.byId.get(o.unit_id) }))
    .sort((a, b) => (b.u?.rarity || 0) - (a.u?.rarity || 0) || b.o.level - a.o.level);
  body.innerHTML = rows
    .map(({ o, index, u }) =>
      u
        ? `<tr><td>${escapeHtml(u.name)}<br><small>${escapeHtml(u.title)}</small></td><td>${u.rarity}</td><td>${dot(u.element)}${u.element}</td>
           <td><input type="number" min="1" max="${maxLevel(u)}" value="${o.level}" data-level="${index}" /></td>
           <td><input type="number" min="0" max="${Math.min(5, (u.abilities || []).length)}" value="${o.dupes || 0}" data-abilities="${index}" title="Abilities unlocked" /></td><td>${costOf(u, o)}</td>
           <td><button type="button" data-remove="${index}" title="Remove">✕</button></td></tr>`
        : `<tr><td colspan="6">Unknown unit #${o.unit_id}</td><td><button type="button" data-remove="${index}">✕</button></td></tr>`,
    )
    .join("");
  const distinct = new Set(state.roster.units.map((o) => o.unit_id)).size;
  $("roster-summary").textContent = state.roster.units.length
    ? `${state.roster.units.length} units (${distinct} different) in this box.`
    : "Your box is empty. Upload a recording, use the example box, or add units by hand.";
}

$("roster").addEventListener("change", (event) => {
  const abilities = event.target.dataset.abilities;
  if (abilities !== undefined) {
    const entry = state.roster.units[Number(abilities)];
    const unit = state.byId.get(entry.unit_id);
    entry.dupes = Math.max(0, Math.min(5, (unit.abilities || []).length, Number(event.target.value) || 0));
    saveRoster();
    return;
  }
  const index = event.target.dataset.level;
  if (index === undefined) return;
  const entry = state.roster.units[Number(index)];
  const unit = state.byId.get(entry.unit_id);
  const level = Math.max(1, Math.min(maxLevel(unit), Number(event.target.value) || 1));
  entry.level = level;
  entry.limit_break = unit.rarity === 6 && level > unit.max_level ? Math.floor((level - unit.max_level) / 5) : 0;
  saveRoster();
});

$("roster").addEventListener("click", (event) => {
  const index = event.target.dataset.remove;
  if (index === undefined) return;
  state.roster.units.splice(Number(index), 1);
  saveRoster();
});

$("profile").addEventListener("change", () => {
  state.profile = $("profile").value.trim();
  localStorage.setItem(`${STORE}profile`, state.profile);
  loadRoster();
});
$("cost-limit").addEventListener("change", saveRoster);

$("add-unit").addEventListener("click", () => {
  const id = idFromLabel($("unit-search").value);
  const unit = state.byId.get(id);
  if (!unit) {
    $("unit-search").setCustomValidity("Pick a unit from the list.");
    $("unit-search").reportValidity();
    return;
  }
  $("unit-search").setCustomValidity("");
  const level = Math.max(1, Math.min(maxLevel(unit), Number($("unit-level").value) || 1));
  state.roster.units.push(owned(id, level, unit.rarity === 6 && level > unit.max_level ? Math.floor((level - unit.max_level) / 5) : 0));
  $("unit-search").value = "";
  saveRoster();
});

$("example").addEventListener("click", async () => {
  if (state.roster.units.length && !confirm("Replace your current box with the example box?")) return;
  state.roster = await (await fetch("data/example-roster.json")).json();
  $("cost-limit").value = state.roster.team_cost_limit || 200;
  saveRoster();
});

$("clear").addEventListener("click", () => {
  if (!confirm("Remove every unit from this box?")) return;
  state.roster.units = [];
  saveRoster();
});

$("export").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(state.roster, null, 2)], { type: "application/json" });
  const link = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob),
    download: `nb-box-${state.profile || "mine"}.json`,
  });
  link.click();
  URL.revokeObjectURL(link.href);
});

$("import").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (!Array.isArray(data.units)) throw new Error("no units list");
    state.roster = { ...emptyRoster(), ...data };
    $("cost-limit").value = state.roster.team_cost_limit || 200;
    saveRoster();
  } catch (error) {
    alert(`That file isn't a box export: ${error.message}`);
  }
  event.target.value = "";
});

// ---------- recording ----------

$("recording").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const panel = $("reader");
  panel.hidden = false;
  $("reader-review").innerHTML = "";
  const status = (text) => ($("reader-status").textContent = text);
  const progress = (value) => ($("reader-progress").value = value);
  try {
    const { readRecording } = await import("./reader.js");
    const readings = await readRecording(file, state.units, { status, progress });
    reviewReadings(readings);
  } catch (error) {
    status(`Couldn't read that recording: ${error.message}`);
  }
});

function reviewReadings(readings) {
  const doubtful = readings.filter((r) => r.problems.length);
  $("reader-status").textContent =
    `Found ${readings.length} units. ` +
    (doubtful.length ? `${doubtful.length} need a quick check below.` : "All of them read cleanly.");
  const review = $("reader-review");
  review.innerHTML = `
    <div class="review">${doubtful
      .map(
        (r) => `<figure><img src="${r.banner}" alt="" /><figcaption>
          <span class="flag">${escapeHtml(r.problems.join("; "))}</span><br />
          <input list="unit-list" data-fix="${r.visit}" value="${r.unit_id ? escapeHtml(unitLabel(state.byId.get(r.unit_id))) : ""}" placeholder="Which unit is this?" />
          <label>Level <input type="number" min="1" max="150" data-fixlevel="${r.visit}" value="${r.level || 1}" /></label>
        </figcaption></figure>`,
      )
      .join("")}</div>
    <div class="row buttons"><button id="accept-reading" type="button" class="primary">Use these ${readings.length} units as my box</button></div>`;
  $("accept-reading").addEventListener("click", () => {
    const units = [];
    for (const r of readings) {
      const fixed = review.querySelector(`[data-fix="${r.visit}"]`);
      const id = fixed ? idFromLabel(fixed.value) : r.unit_id;
      const levelInput = review.querySelector(`[data-fixlevel="${r.visit}"]`);
      const level = levelInput ? Number(levelInput.value) : r.level;
      const unit = state.byId.get(id);
      if (!unit || !level) continue;
      const lb = unit.rarity === 6 && level > unit.max_level ? Math.floor((level - unit.max_level) / 5) : 0;
      units.push({ ...owned(id, level, lb), manually_added: Boolean(fixed) });
    }
    state.roster.units = units;
    saveRoster();
    $("reader").hidden = true;
  });
}

// ---------- missions ----------

function renderMissions() {
  const query = $("mission-search").value.trim().toLowerCase();
  const list = $("mission");
  const current = list.value;
  list.innerHTML = state.missions
    .filter((m) => !query || m.name.toLowerCase().includes(query) || m.stages.some((s) => s.name.toLowerCase().includes(query) || (s.boss || "").toLowerCase().includes(query)))
    .map((m) => `<option value="${m.slug}">${escapeHtml(m.name)} · ${m.mode}</option>`)
    .join("");
  if (current) list.value = current;
}

function selectedMission() {
  return state.missions.find((m) => m.slug === $("mission").value);
}

function renderStages() {
  const mission = selectedMission();
  $("stage").innerHTML = mission
    ? mission.stages.map((s, i) => `<option value="${i}">${escapeHtml(s.name)} · ${s.stamina} stamina${s.boss ? ` · boss ${escapeHtml(s.boss)}` : ""}</option>`).join("")
    : "";
  renderObjectives();
}

function renderObjectives() {
  const mission = selectedMission();
  const stage = mission?.stages[Number($("stage").value) || 0];
  $("objective").innerHTML = stage?.conditions.length
    ? stage.conditions.map((c, i) => `<option value="${i}">${escapeHtml(c.description)}${c.pearls ? ` (${c.pearls} pearls)` : ""}</option>`).join("")
    : `<option value="-1">No objectives listed for this stage</option>`;
  const complete = document.querySelector('input[name="goal"]:checked').value === "complete";
  $("objective").disabled = !complete || !stage?.conditions.length;
}

$("mission-search").addEventListener("input", renderMissions);
$("mission").addEventListener("change", renderStages);
$("stage").addEventListener("change", renderObjectives);
document.querySelectorAll('input[name="goal"]').forEach((r) => r.addEventListener("change", renderObjectives));
$("helper-mode").addEventListener("change", () => ($("helper-search").hidden = $("helper-mode").value !== "pick"));

// ---------- solving ----------

const worker = new Worker("worker.js", { type: "module" });
const pending = new Map();
worker.onmessage = (event) => {
  const message = event.data;
  if (message.type === "status") $("engine-status").textContent = message.text;
  if (message.type === "ready") $("engine-status").textContent = `Solver ready (${message.units} units loaded).`;
  if (message.type === "progress") {
    $("solve-progress").value = message.done / message.total;
    $("engine-status").textContent = `Testing teams… ${message.done} of ${message.total}`;
  }
  if (message.type === "result" || message.type === "error") {
    const done = pending.get(message.id);
    pending.delete(message.id);
    if (done) done(message);
  }
};

$("solve").addEventListener("click", () => {
  const mission = selectedMission();
  if (!mission) return alert("Pick a mission first.");
  if (!state.roster.units.length) return alert("Your box is empty — add some units first.");
  const stage = mission.stages[Number($("stage").value) || 0];
  const complete = document.querySelector('input[name="goal"]:checked').value === "complete";
  let helper = $("helper-mode").value;
  if (helper === "pick") {
    helper = idFromLabel($("helper-search").value);
    if (!helper) return alert("Pick a helper unit from the list, or choose auto.");
  }
  const id = ++state.solving;
  $("solve").disabled = true;
  $("solve-progress").hidden = false;
  $("solve-progress").value = 0;
  pending.set(id, (message) => {
    $("solve").disabled = false;
    $("solve-progress").hidden = true;
    if (message.type === "error") {
      $("engine-status").textContent = `Something went wrong: ${message.text}`;
      return;
    }
    $("engine-status").textContent = "Done.";
    renderResult(message.result, mission, stage);
  });
  worker.postMessage({
    type: "solve",
    id,
    slug: mission.slug,
    stage: stage.name,
    roster: { ...state.roster, team_cost_limit: Number($("cost-limit").value) || 200 },
    condition: complete ? Number($("objective").value) : -1,
    helper,
    tries: Number($("tries").value),
  });
});

function unitCard(slot, c) {
  return `<div class="unit"><div class="slot">${slot}</div><div class="name">${dot(c.element)}${escapeHtml(c.name)}</div>
    <div class="title">${escapeHtml(c.title)} · ${c.rarity}★ · Lv ${c.level}${c.helper ? "" : ` · cost ${c.cost}`}</div></div>`;
}

function renderResult(report, mission, stage) {
  $("result-panel").hidden = false;
  const verdict = $("verdict");
  if (report.status === "found") {
    const pct = Math.round(report.likelihood * 100);
    verdict.innerHTML = `<p class="verdict good">Clear likelihood ${pct}%</p>
      <p class="hint">95% range ${Math.round(report.interval[0] * 100)}–${Math.round(report.interval[1] * 100)}% over ${report.tries} simulated attempts${report.median_turns ? ` · typically ${report.median_turns} turns` : ""}.</p>`;
  } else if (report.status === "not_found") {
    verdict.innerHTML = `<p class="verdict bad">${escapeHtml(report.message)}</p>
      <p class="hint">Best team below won 0 of ${report.tries} simulated attempts. That is not proof it can't be done — see the suggestions.</p>`;
  } else if (report.status === "impossible") {
    verdict.innerHTML = `<p class="verdict bad">${escapeHtml(report.message)}</p><p>${escapeHtml(report.reason || "")}</p>`;
  } else {
    verdict.innerHTML = `<p class="verdict bad">${escapeHtml(report.message || "Couldn't solve this one.")}</p>`;
  }

  const team = report.team;
  $("team").innerHTML = team
    ? `<div class="teams">${team.front.map((c) => unitCard("Front", c)).join("")}${team.helper ? unitCard("Helper", team.helper) : ""}${team.back
        .map((c) => unitCard("Support", c))
        .join("")}</div><p class="hint">Team cost ${team.cost} / ${team.cost_limit}.</p>`
    : "";

  const showcase = report.showcase;
  $("playback").hidden = !showcase || !showcase.frames.length;
  if (showcase && showcase.frames.length) {
    state.playback?.pause();
    state.playback = new Playback($("grid"), $("caption"), report);
    $("scrub").max = showcase.frames.length - 1;
    $("scrub").value = 0;
    $("steps").innerHTML = showcase.frames.map((f) => `<li>Turn ${f.turn} (map ${f.map}): ${escapeHtml(f.instruction)}</li>`).join("");
    state.playback.go(0);
    syncSteps();
  }

  $("depends").innerHTML = report.depends_on?.length
    ? `<h3>What it depends on</h3><ul>${report.depends_on.map((d) => `<li>${escapeHtml(d)}</li>`).join("")}</ul>`
    : "";
  $("advice").innerHTML = report.recommendations?.length
    ? `<h3>Least grinding that could get you there</h3><ol>${report.recommendations
        .map((r) => `<li>${escapeHtml(r.step)} — simulated clear rate ${Math.round(r.likelihood * 100)}%</li>`)
        .join("")}</ol>`
    : "";
  const assumptions = $("assumptions");
  assumptions.hidden = !report.assumptions?.length;
  assumptions.querySelector("ul").innerHTML = (report.assumptions || []).map((a) => `<li>${escapeHtml(a)}</li>`).join("");
  $("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function syncSteps() {
  const index = state.playback?.index ?? 0;
  $("scrub").value = index;
  $("steps").querySelectorAll("li").forEach((li, i) => li.classList.toggle("current", i === index));
}

$("first").addEventListener("click", () => { state.playback?.go(0); syncSteps(); });
$("back").addEventListener("click", () => { state.playback?.prev(); syncSteps(); });
$("forward").addEventListener("click", () => { state.playback?.next(); syncSteps(); });
$("scrub").addEventListener("input", () => { state.playback?.go(Number($("scrub").value)); syncSteps(); });
$("play").addEventListener("click", () => {
  const playback = state.playback;
  if (!playback) return;
  if (playback.timer) {
    playback.pause();
    return;
  }
  $("play").textContent = "⏸ Pause";
  playback.play(() => ($("play").textContent = "▶ Play"));
  const follow = setInterval(() => {
    syncSteps();
    if (!playback.timer) clearInterval(follow);
  }, 200);
});
window.addEventListener("resize", () => state.playback?.draw(1));

// ---------- start ----------

async function start() {
  $("profile").value = state.profile;
  const [units, missions] = await Promise.all([
    fetch("data/units.json").then((r) => r.json()),
    fetch("data/missions/index.json").then((r) => r.json()),
  ]);
  state.units = units;
  state.byId = new Map(units.map((u) => [u.unit_id, u]));
  state.missions = missions;
  $("unit-list").innerHTML = units
    .filter((u) => u.rarity >= 3)
    .map((u) => `<option value="${escapeHtml(unitLabel(u))}"></option>`)
    .join("");
  renderMissions();
  loadRoster();
}

start();
