// Runs the browser reader's own code over the labelled recordings and scores it.
//   node validate_reader.mjs
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import Tesseract from "tesseract.js";
import { PNG } from "pngjs";
import { assess, countStars, levelImage, textImage, NAME_ROWS, TITLE_ROWS } from "../web/readercore.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const ANALYSIS = join(ROOT, "data", "analysis");
const units = JSON.parse(readFileSync(join(ROOT, "data", "units.json"), "utf8")).filter((u) => (u.rarity || 0) >= 4);
const truth = JSON.parse(readFileSync(join(ANALYSIS, "visits_v2_truth.json"), "utf8"));

const png = (image) => PNG.sync.write({ width: image.width, height: image.height, data: Buffer.from(image.data.buffer) });

const text = await Tesseract.createWorker("eng");
await text.setParameters({ tessedit_pageseg_mode: Tesseract.PSM.SINGLE_LINE });
const digits = await Tesseract.createWorker("eng");
await digits.setParameters({ tessedit_pageseg_mode: Tesseract.PSM.SINGLE_LINE, tessedit_char_whitelist: "0123456789/MAX" });

async function readDir(name) {
  const dir = join(ANALYSIS, name);
  const files = readdirSync(dir).filter((f) => f.endsWith(".png")).sort();
  const out = [];
  for (const file of files) {
    const decoded = PNG.sync.read(readFileSync(join(dir, file)));
    const page = { width: decoded.width, height: decoded.height, data: new Uint8ClampedArray(decoded.data) };
    const rawName = (await text.recognize(png(textImage(page, NAME_ROWS)))).data.text.trim();
    const rawTitle = (await text.recognize(png(textImage(page, TITLE_ROWS)))).data.text.trim();
    const rawLevel = (await digits.recognize(png(levelImage(page)))).data.text.trim();
    out.push({ page: file, ...assess({ rawName, rawTitle, rawLevel, stars: countStars(page) }, units) });
    process.stdout.write(".");
  }
  process.stdout.write("\n");
  return out;
}

const key = (r) => [r.name, r.title, r.rarity, r.level, r.level_cap].join("|");

const v2 = await readDir("visits_v2");
let exact = 0;
const wrong = [];
v2.forEach((r, i) => {
  if (key(r) === key(truth[i])) exact++;
  else wrong.push({ visit: i, read: key(r), truth: key(truth[i]), raw: [r.raw_name, r.raw_title, r.raw_level], flagged: r.problems });
});
console.log(`v2: ${exact}/${v2.length} exact; flagged ${v2.filter((r) => r.problems.length).length}; min margin ${Math.min(...v2.map((r) => r.margin)).toFixed(3)}`);
for (const w of wrong) console.log("  WRONG", JSON.stringify(w));

const v1 = await readDir("visits_v1run");
const count = (list) => list.reduce((m, r) => m.set(key(r), (m.get(key(r)) || 0) + 1), new Map());
const a = count(v1);
const b = count(truth);
const diff = [...new Set([...a.keys(), ...b.keys()])].filter((k) => (a.get(k) || 0) !== (b.get(k) || 0));
console.log(`run1 (held out): ${v1.length} pages; multiset differences vs labels: ${diff.length}; flagged ${v1.filter((r) => r.problems.length).length}`);
for (const k of diff) console.log("  DIFF", k, "read", a.get(k) || 0, "labelled", b.get(k) || 0);

// A silent misread is the failure that matters: wrong and not flagged.
const silent = wrong.filter((w) => !w.flagged.length).length;
console.log(`silent misreads on v2: ${silent}`);
writeFileSync(join(ANALYSIS, "reader_js_validation.json"), JSON.stringify({ v2, v1 }, null, 2));
await text.terminate();
await digits.terminate();
