// Pure image and text logic for reading a box recording. No DOM, so the very
// same code runs in the browser and in the Node validation script.

// Geometry measured on 1180x2556 recordings; other sizes are scaled from it.
export const BASE = { width: 1180, height: 2556 };
export const TEXT_COLS = [215, 830];
export const NAME_ROWS = [558, 616];
export const TITLE_ROWS = [622, 660];
export const STAR_BOX = [215, 500, 830, 545];
export const LEVEL_BOX = [470, 1696, 720, 1744];
export const BANNER_BOX = [170, 500, 830, 670];
export const SCAN_ROWS = [130, 2300];
export const WHITE = 170;
export const BRIGHT = 170;
export const STAR_AREA = 120;
export const DARK = 10;
export const CLEAR = 0.15;
const SIX_STAR_STEP = 5;

export function scaleBox([x0, y0, x1, y1], width, height) {
  const sx = width / BASE.width;
  const sy = height / BASE.height;
  return [Math.round(x0 * sx), Math.round(y0 * sy), Math.round(x1 * sx), Math.round(y1 * sy)];
}

export function crop(image, [x0, y0, x1, y1]) {
  const width = x1 - x0;
  const height = y1 - y0;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    const from = ((y0 + y) * image.width + x0) * 4;
    data.set(image.data.subarray(from, from + width * 4), y * width * 4);
  }
  return { width, height, data };
}

function greyOf(image, pick) {
  const out = new Float32Array(image.width * image.height);
  const d = image.data;
  for (let i = 0, p = 0; i < out.length; i++, p += 4) out[i] = pick(d[p], d[p + 1], d[p + 2]);
  return out;
}

function upscaleBilinear(grey, width, height, factor) {
  const w = width * factor;
  const h = height * factor;
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    const sy = Math.min(height - 1, Math.max(0, (y + 0.5) / factor - 0.5));
    const y0 = Math.floor(sy);
    const y1 = Math.min(height - 1, y0 + 1);
    const fy = sy - y0;
    for (let x = 0; x < w; x++) {
      const sx = Math.min(width - 1, Math.max(0, (x + 0.5) / factor - 0.5));
      const x0 = Math.floor(sx);
      const x1 = Math.min(width - 1, x0 + 1);
      const fx = sx - x0;
      const top = grey[y0 * width + x0] * (1 - fx) + grey[y0 * width + x1] * fx;
      const bottom = grey[y1 * width + x0] * (1 - fx) + grey[y1 * width + x1] * fx;
      out[y * w + x] = top * (1 - fy) + bottom * fy;
    }
  }
  return { grey: out, width: w, height: h };
}

function upscaleNearest(grey, width, height, factor) {
  const w = width * factor;
  const h = height * factor;
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) out[y * w + x] = grey[Math.floor(y / factor) * width + Math.floor(x / factor)];
  }
  return { grey: out, width: w, height: h };
}

// Black ink on white, padded, as an RGBA image Tesseract can read.
function inked({ grey, width, height }, isInk, pad = 20) {
  const w = width + pad * 2;
  const h = height + pad * 2;
  const data = new Uint8ClampedArray(w * h * 4).fill(255);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!isInk(grey[y * width + x])) continue;
      const p = ((y + pad) * w + x + pad) * 4;
      data[p] = data[p + 1] = data[p + 2] = 0;
    }
  }
  return { width: w, height: h, data };
}

export function textImage(page, rows) {
  const box = scaleBox([TEXT_COLS[0], rows[0], TEXT_COLS[1], rows[1]], page.width, page.height);
  const part = crop(page, box);
  const grey = greyOf(part, (r, g, b) => Math.min(r, g, b));
  return inked(upscaleBilinear(grey, part.width, part.height, 2), (v) => v > WHITE);
}

export function levelImage(page) {
  const part = crop(page, scaleBox(LEVEL_BOX, page.width, page.height));
  const grey = greyOf(part, (r, g, b) => Math.max(r, g, b));
  return inked(upscaleNearest(grey, part.width, part.height, 2), (v) => v >= BRIGHT);
}

// OpenCV's 8-bit HSV: hue 0-179, saturation and value 0-255.
function hsv(r, g, b) {
  const v = Math.max(r, g, b);
  const low = Math.min(r, g, b);
  const span = v - low;
  const s = v === 0 ? 0 : (span * 255) / v;
  let h = 0;
  if (span > 0) {
    if (v === r) h = (60 * (g - b)) / span;
    else if (v === g) h = 120 + (60 * (b - r)) / span;
    else h = 240 + (60 * (r - g)) / span;
    if (h < 0) h += 360;
  }
  return [h / 2, s, v];
}

export function countStars(page) {
  const part = crop(page, scaleBox(STAR_BOX, page.width, page.height));
  const { width, height, data } = part;
  const lit = new Uint8Array(width * height);
  for (let i = 0, p = 0; i < lit.length; i++, p += 4) {
    const [h, s, v] = hsv(data[p], data[p + 1], data[p + 2]);
    lit[i] = h >= 18 && h <= 35 && s >= 120 && v >= 200 ? 1 : 0;
  }
  const minimum = STAR_AREA * (page.width / BASE.width) * (page.height / BASE.height);
  const seen = new Uint8Array(lit.length);
  let stars = 0;
  for (let start = 0; start < lit.length; start++) {
    if (!lit[start] || seen[start]) continue;
    let area = 0;
    const stack = [start];
    seen[start] = 1;
    while (stack.length) {
      const i = stack.pop();
      area++;
      const x = i % width;
      const y = (i - x) / width;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
          const j = ny * width + nx;
          if (lit[j] && !seen[j]) {
            seen[j] = 1;
            stack.push(j);
          }
        }
      }
    }
    if (area >= minimum) stars++;
  }
  return stars;
}

export function brightness(page) {
  const [, y0, , y1] = scaleBox([0, SCAN_ROWS[0], 0, SCAN_ROWS[1]], page.width, page.height);
  let total = 0;
  let count = 0;
  for (let y = y0; y < Math.min(y1, page.height); y += 1) {
    for (let x = 0; x < page.width; x += 1) {
      const p = (y * page.width + x) * 4;
      total += page.data[p] + page.data[p + 1] + page.data[p + 2];
      count += 3;
    }
  }
  return count ? total / count : 0;
}

export function sharpness(page, box = BANNER_BOX) {
  const part = crop(page, scaleBox(box, page.width, page.height));
  const grey = greyOf(part, (r, g, b) => 0.299 * r + 0.587 * g + 0.114 * b);
  const { width, height } = part;
  let sum = 0;
  let squares = 0;
  let n = 0;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const lap = grey[i - 1] + grey[i + 1] + grey[i - width] + grey[i + width] - 4 * grey[i];
      sum += lap;
      squares += lap * lap;
      n++;
    }
  }
  return n ? squares / n - (sum / n) ** 2 : 0;
}

// ---------- text ----------

export function normalise(text) {
  return Array.from(String(text).toLowerCase())
    .filter((c) => /[\p{L}\p{N}]/u.test(c))
    .join("");
}

// Python's difflib.SequenceMatcher(None, a, b).ratio(), for strings under 200.
export function ratio(a, b) {
  if (!a.length && !b.length) return 1;
  const where = new Map();
  for (let j = 0; j < b.length; j++) {
    if (!where.has(b[j])) where.set(b[j], []);
    where.get(b[j]).push(j);
  }
  const longest = (alo, ahi, blo, bhi) => {
    let besti = alo;
    let bestj = blo;
    let best = 0;
    let lengths = new Map();
    for (let i = alo; i < ahi; i++) {
      const next = new Map();
      for (const j of where.get(a[i]) || []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (lengths.get(j - 1) || 0) + 1;
        next.set(j, k);
        if (k > best) {
          besti = i - k + 1;
          bestj = j - k + 1;
          best = k;
        }
      }
      lengths = next;
    }
    return [besti, bestj, best];
  };
  let matched = 0;
  const queue = [[0, a.length, 0, b.length]];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop();
    const [i, j, k] = longest(alo, ahi, blo, bhi);
    if (!k) continue;
    matched += k;
    if (alo < i && blo < j) queue.push([alo, i, blo, j]);
    if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
  }
  return (2 * matched) / (a.length + b.length);
}

export function similarity(a, b) {
  return ratio(normalise(a), normalise(b));
}

export function identify(name, title, rarity, units) {
  const pool = units.filter((u) => u.rarity === rarity);
  const n = normalise(name);
  const t = normalise(title);
  let best = null;
  let first = -1;
  let second = -1;
  for (const unit of pool) {
    const score = (ratio(n, normalise(unit.name)) + ratio(t, normalise(unit.title || ""))) / 2;
    if (score > first) {
      second = first;
      first = score;
      best = unit;
    } else if (score > second) {
      second = score;
    }
  }
  if (!best) return { unit: null, match: 0, margin: 0 };
  return { unit: best, match: first, margin: first - Math.max(0, second) };
}

export function parseLevel(text) {
  const match = /(M?A?X|\d{1,3})\/(\d{2,3})/.exec(String(text).replace(/\s+/g, ""));
  if (!match) return null;
  const cap = Number(match[2]);
  const current = match[1].includes("X") ? cap : Number(match[1]);
  return [current, cap];
}

export function limitBreaks(unit, cap) {
  if (cap === unit.max_level) return 0;
  if (unit.rarity === 6) return Math.floor((cap - unit.max_level) / SIX_STAR_STEP);
  return null;
}

export function assess({ rawName, rawTitle, rawLevel, stars }, units) {
  const { unit, match, margin } = identify(rawName, rawTitle, stars, units);
  const problems = [];
  if (!unit) problems.push(`no ${stars}-star unit to match`);
  else if (margin < CLEAR) problems.push(`close call (lead ${margin.toFixed(2)})`);

  const level = parseLevel(rawLevel);
  let current = null;
  let cap = null;
  let breaks = null;
  if (!level) problems.push(`level unreadable: "${rawLevel}"`);
  else {
    [current, cap] = level;
    if (unit) {
      const low = unit.max_level;
      const high = unit.max_level_limit_break || unit.max_level;
      if (cap < low || cap > high) problems.push(`level cap ${cap} outside ${low}-${high}`);
      else {
        breaks = limitBreaks(unit, cap);
        if (breaks === null) problems.push(`limit breaks unknown for ${unit.rarity}-star cap ${cap}`);
      }
      if (current > cap) problems.push(`level ${current} above cap ${cap}`);
    }
  }
  return {
    unit_id: unit ? unit.unit_id : null,
    name: unit ? unit.name : "",
    title: unit ? unit.title : "",
    rarity: stars,
    level: current,
    level_cap: cap,
    limit_break: breaks,
    match: Math.round(match * 1000) / 1000,
    margin: Math.round(margin * 1000) / 1000,
    raw_name: rawName,
    raw_title: rawTitle,
    raw_level: rawLevel,
    problems,
  };
}

// Runs of non-black samples, each one unit's page. Samples are [seconds, brightness].
export function visits(samples, minimumSeconds = 0.5) {
  const out = [];
  let start = null;
  for (let i = 0; i < samples.length; i++) {
    const lit = samples[i][1] >= DARK;
    if (lit && start === null) start = i;
    if (!lit && start !== null) {
      out.push([start, i - 1]);
      start = null;
    }
  }
  if (start !== null) out.push([start, samples.length - 1]);
  return out
    .filter(([a, b]) => samples[b][0] - samples[a][0] >= minimumSeconds)
    .map(([a, b]) => samples.slice(a, b + 1));
}

// Times worth looking at closely: spread across the full-brightness part.
export function candidateTimes(visit) {
  const peak = Math.max(...visit.map((s) => s[1]));
  const steady = visit.filter((s) => s[1] >= 0.97 * peak);
  const pick = (f) => steady[Math.min(steady.length - 1, Math.floor(f * steady.length))][0];
  return [...new Set([pick(0.3), pick(0.5), pick(0.7)])];
}
