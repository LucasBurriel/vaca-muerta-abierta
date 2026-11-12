// Loads site/js/i18n.js under Node in the language given as argv[2] (no DOM), for tests/test_i18n.py.
// Prints: the language, the locale, a few t() results, a formatted number and what enlace() does.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

globalThis.__VMA_LANG = process.argv[2];
globalThis.__VMA_LANG_EXPLICITO = process.argv[3] === "explicito";
const aqui = dirname(fileURLToPath(import.meta.url));
const fuente = readFileSync(join(aqui, "..", "..", "site", "js", "i18n.js"), "utf8");
const I = await import("data:text/javascript;base64," + Buffer.from(fuente, "utf8").toString("base64"));

process.stdout.write(
  JSON.stringify({
    lang: I.LANG,
    locale: I.LOCALE,
    n_claves: Object.keys(I.EN).length,
    simple: I.t("nav.curvas", "Curvas tipo"),
    con_variable: I.t("curvas.th.mes", "mes {m}", { m: 12 }),
    sin_clave: I.t("no.existe", "texto {x} en español", { x: 7 }),
    variable_ausente: I.t("curvas.th.mes", "mes {m}"),
    numero: new Intl.NumberFormat(I.LOCALE, { maximumFractionDigits: 1 }).format(1234567.8),
    enlaces: ["simulador.html", "metodo.html#reglas", "curvas.html?x=1", "https://example.org/a.html", "#ancla", "index.html?lang=es"].map(I.enlace),
  }),
);
