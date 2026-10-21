// Runs the Python solver off the main thread so the page stays responsive.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";

let ready = null;

function post(message) {
  self.postMessage(message);
}

async function boot() {
  const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
  post({ type: "status", text: "Loading Python…" });
  const pyodide = await loadPyodide({ indexURL: PYODIDE });
  post({ type: "status", text: "Loading pydantic…" });
  await pyodide.loadPackage("pydantic");
  post({ type: "status", text: "Loading the engine…" });
  const engine = await fetch("py/nbsolver.zip");
  pyodide.unpackArchive(await engine.arrayBuffer(), "zip", { extractDir: "/home/pyodide/lib" });
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide/lib')");
  const api = pyodide.pyimport("nbsolver.webapi");
  post({ type: "status", text: "Loading units…" });
  const units = await (await fetch("data/units.json")).text();
  const count = api.load_units(units);
  post({ type: "ready", units: count });
  return { pyodide, api };
}

self.onmessage = async (event) => {
  const message = event.data;
  try {
    ready =
      ready ||
      boot().catch((error) => {
        ready = null;
        throw error;
      });
    const { api } = await ready;
    if (message.type !== "solve") return;
    const mission = await (await fetch(`data/missions/${message.slug}.json`)).text();
    const progress = (done, total) => post({ type: "progress", id: message.id, done, total });
    const result = api.solve_json(
      mission,
      message.stage,
      JSON.stringify(message.roster),
      message.condition,
      String(message.helper),
      message.tries,
      progress,
    );
    post({ type: "result", id: message.id, result: JSON.parse(result) });
  } catch (error) {
    post({ type: "error", id: message.id, text: String(error && error.message ? error.message : error) });
  }
};
