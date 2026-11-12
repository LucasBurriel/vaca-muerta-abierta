// Runs the browser Monte Carlo core (site/js/montecarlo.js) under Node, for tests/test_simulador_js.py.
// Usage: node tests/js/correr_montecarlo.mjs <params.json>   -> one JSON document on stdout.
// The core is loaded through a data: URL so it runs as an ES module on any Node (the site has no package.json).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const aqui = dirname(fileURLToPath(import.meta.url));
const fuente = readFileSync(join(aqui, "..", "..", "site", "js", "montecarlo.js"), "utf8");
const MC = await import("data:text/javascript;base64," + Buffer.from(fuente, "utf8").toString("base64"));

const params = JSON.parse(readFileSync(process.argv[2], "utf8"));
const salida = { casos: [] };
for (const caso of params.casos) {
  const t0 = performance.now();
  const r = MC.simular(caso);
  // the same run in chunks must give the same numbers (the page runs it chunked)
  const sim = MC.iniciar(caso);
  while (sim.hechas() < sim.total) sim.correr(7);
  const r2 = sim.resultado();
  salida.casos.push({ resultado: r, igual_por_partes: JSON.stringify(r) === JSON.stringify(r2), ms: performance.now() - t0 });
}
salida.percentil = [MC.percentilOrdenado(Float64Array.from([1, 2, 3, 4]), 50), MC.percentilOrdenado(Float64Array.from([1, 2, 3, 4]), 90)];
salida.inversa = [10, 50, 90, 30].map((u) => MC.tasaDesdePercentil(u, 150, 100, 50));
salida.inicios = MC.inicios(10, 4);
const a = MC.crearRng(7), b = MC.crearRng(7);
salida.rng_reproducible = [a.uniforme(), a.normal(), a.normal()].join() === [b.uniforme(), b.normal(), b.normal()].join();
process.stdout.write(JSON.stringify(salida));
