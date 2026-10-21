// Top-down replay of one solved run, one action per step.
const DAMAGE = { red: "#ff4d4d", grey: "#c8c8c8", blue: "#4da3ff", purple: "#b36bff", green: "#4dd27a" };
const ELEMENT = { Heart: "#e8506a", Skill: "#3fbf6a", Body: "#e6b422", Bravery: "#3f8fe8", Wisdom: "#a46be8" };
const MOVE_MS = 450;
const FLOAT_MS = 900;

export class Playback {
  constructor(canvas, caption, report) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.caption = caption;
    this.report = report;
    this.frames = report.showcase.frames;
    this.roster = report.showcase.roster;
    this.grids = report.grids || [];
    this.index = 0;
    this.timer = null;
    this.anim = null;
    this.draw(1);
  }

  grid(map) {
    return this.grids[map - 1] || { columns: 9, rows: 10 };
  }

  previousPositions(index) {
    if (index <= 0) return {};
    const before = this.frames[index - 1];
    const now = this.frames[index];
    return before.map === now.map ? before.positions : {};
  }

  go(index) {
    if (!this.frames.length) return;
    this.index = Math.max(0, Math.min(this.frames.length - 1, index));
    const start = performance.now();
    cancelAnimationFrame(this.anim);
    const tick = (now) => {
      const t = Math.min(1, (now - start) / (MOVE_MS + FLOAT_MS));
      this.draw(t);
      if (t < 1) this.anim = requestAnimationFrame(tick);
    };
    this.anim = requestAnimationFrame(tick);
  }

  next() {
    if (this.index < this.frames.length - 1) this.go(this.index + 1);
    else this.pause();
  }

  prev() {
    this.go(this.index - 1);
  }

  play(onStop) {
    this.pause();
    this.onStop = onStop;
    this.timer = setInterval(() => this.next(), MOVE_MS + FLOAT_MS);
  }

  pause() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (this.onStop) this.onStop();
  }

  draw(t) {
    const frame = this.frames[this.index];
    if (!frame) return;
    const { columns, rows } = this.grid(frame.map);
    const ctx = this.ctx;
    const width = this.canvas.clientWidth || 360;
    const cell = Math.floor(width / (columns + 1));
    const height = cell * (rows + 1) + 34;
    const ratio = window.devicePixelRatio || 1;
    if (this.canvas.width !== width * ratio || this.canvas.height !== height * ratio) {
      this.canvas.width = width * ratio;
      this.canvas.height = height * ratio;
      this.canvas.style.height = `${height}px`;
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const top = 34;
    const offset = cell / 2;
    const at = ([x, y]) => [offset + x * cell + cell / 2, top + offset + y * cell + cell / 2];

    // Team health across the top.
    const max = this.report.showcase.max_health || 1;
    ctx.fillStyle = "#2a2f3a";
    ctx.fillRect(8, 8, width - 16, 16);
    ctx.fillStyle = frame.team_health / max > 0.3 ? "#4dd27a" : "#ff4d4d";
    ctx.fillRect(8, 8, (width - 16) * Math.max(0, frame.team_health / max), 16);
    ctx.fillStyle = "#fff";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`Team HP ${frame.team_health} / ${max}   ·   Map ${frame.map}, wave ${frame.wave}   ·   Turn ${frame.turn}`, 14, 20);

    ctx.strokeStyle = "#2c3340";
    for (let c = 0; c <= columns; c++) {
      ctx.beginPath();
      ctx.moveTo(offset + c * cell, top + offset);
      ctx.lineTo(offset + c * cell, top + offset + rows * cell);
      ctx.stroke();
    }
    for (let r = 0; r <= rows; r++) {
      ctx.beginPath();
      ctx.moveTo(offset, top + offset + r * cell);
      ctx.lineTo(offset + columns * cell, top + offset + r * cell);
      ctx.stroke();
    }

    const before = this.previousPositions(this.index);
    const move = Math.min(1, t * ((MOVE_MS + FLOAT_MS) / MOVE_MS));
    const centre = {};
    for (const [key, pos] of Object.entries(frame.positions)) {
      const from = before[key] || pos;
      const p = [from[0] + (pos[0] - from[0]) * move, from[1] + (pos[1] - from[1]) * move];
      centre[key] = at(p);
      const info = this.roster[key] || {};
      const [x, y] = centre[key];
      const radius = cell * (info.boss ? 0.42 : 0.32);
      ctx.fillStyle = ELEMENT[info.element] || "#888";
      ctx.strokeStyle = key === frame.actor ? "#fff" : "#111";
      ctx.lineWidth = key === frame.actor ? 3 : 1.5;
      ctx.beginPath();
      if (info.enemy) ctx.rect(x - radius, y - radius, radius * 2, radius * 2);
      else ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.lineWidth = 1;
      ctx.fillStyle = "#0b0e14";
      ctx.font = `bold ${Math.max(9, cell * 0.22)}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(initials(info.name || key), x, y + 4);
      ctx.textAlign = "left";
      if (info.enemy && info.max_health) {
        const share = Math.max(0, (frame.enemy_health[key] ?? info.max_health) / info.max_health);
        ctx.fillStyle = "#300";
        ctx.fillRect(x - radius, y + radius + 3, radius * 2, 4);
        ctx.fillStyle = "#ff4d4d";
        ctx.fillRect(x - radius, y + radius + 3, radius * 2 * share, 4);
      }
    }

    // Numbers float up once the move has finished.
    if (t * (MOVE_MS + FLOAT_MS) > MOVE_MS) {
      const f = (t * (MOVE_MS + FLOAT_MS) - MOVE_MS) / FLOAT_MS;
      const seen = {};
      for (const event of frame.events) {
        if (!["damage", "heal", "slip"].includes(event.kind)) continue;
        const key = event.target;
        const spot = centre[key] || centre[frame.actor] || [width / 2, top + 20];
        const stack = (seen[key] = (seen[key] || 0) + 1);
        ctx.globalAlpha = 1 - f * 0.7;
        ctx.fillStyle = DAMAGE[event.colour] || "#fff";
        ctx.font = `bold ${Math.max(12, cell * 0.3)}px system-ui, sans-serif`;
        const label = `${event.kind === "heal" ? "+" : ""}${Math.round(event.amount || 0)}${(event.note || "").includes("critical") ? "!" : ""}`;
        ctx.fillText(label, spot[0] + 6, spot[1] - cell * 0.35 - f * 18 - (stack - 1) * 14);
        ctx.globalAlpha = 1;
      }
    }

    this.caption.textContent = `Turn ${frame.turn}: ${frame.instruction}`;
  }
}

function initials(name) {
  const clean = name.replace(/'.*$/, "").replace(/\(helper\)/, "").trim();
  const parts = clean.split(/\s+/);
  return (parts[0][0] + (parts[1] ? parts[1][0] : parts[0][1] || "")).toUpperCase();
}
