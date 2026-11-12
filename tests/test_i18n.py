"""The site in two languages (ADR-037): Spanish in the HTML and in the JS calls, English in site/js/i18n.js.

Static contract, no browser: every key used anywhere has its English, the English keeps the same {variables},
every page carries the language switch and the early language script, and the simulator's caveats are there in
both languages. With Node, t() and enlace() are exercised too.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PAGINAS = ("index", "explorador", "curvas", "simulador", "mapa", "metodo")
RESUMEN_TARJETAS = re.compile(r'tarjeta\(R, "(\w+)"')


def _leer(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _en() -> dict[str, str]:
    """The EN dictionary, read as text: one `"key": "english",` per line."""
    src = _leer(SITE / "js" / "i18n.js")
    cuerpo = src[src.index("export const EN = {") : src.index("\n};", src.index("export const EN = {"))]
    d = {}
    for m in re.finditer(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', cuerpo, re.M):
        assert m.group(1) not in d, f"duplicate key {m.group(1)}"
        d[m.group(1)] = json.loads(f'"{m.group(2)}"')
    return d


def _claves_html() -> dict[str, str]:
    """key -> Spanish source, for every data-i18n element and data-i18n-attr attribute of the six pages."""
    out = {}
    for pagina in PAGINAS:
        s = _leer(SITE / f"{pagina}.html")
        for m in re.finditer(r'<(\w+)\b[^>]*?\bdata-i18n="([^"]+)"[^>]*>(.*?)</\1>', s, re.S):
            out.setdefault(m.group(2), re.sub(r"\s+", " ", m.group(3)).strip())
        for m in re.finditer(r'<[^>]*\bdata-i18n-attr="([^"]+)"[^>]*>', s):
            for par in m.group(1).split(";"):
                attr, clave = (x.strip() for x in par.split(":"))
                valor = re.search(rf'\b{attr}="([^"]*)"', m.group(0))
                assert valor, f"{pagina}.html: data-i18n-attr names {attr}, which the element does not have"
                out.setdefault(clave, valor.group(1))
    return out


def _claves_js() -> dict[str, str]:
    """key -> Spanish source, for every t("key", "español" ...) call outside i18n.js."""
    out = {}
    for js in sorted((SITE / "js").glob("*.js")):
        if js.name == "i18n.js":
            continue
        for m in re.finditer(
            r'\bt\(\s*"([^"]+)",\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')', _leer(js)
        ):
            es = m.group(2) if m.group(2) is not None else m.group(3)
            previo = out.setdefault(m.group(1), es)
            assert previo == es, f"key {m.group(1)} is used with two different Spanish texts"
    return out


def _claves_dinamicas() -> dict[str, str]:
    """The families comun.js builds with a prefix (column labels, rate labels, flags) and inicio.js's rules."""
    c = _leer(SITE / "js" / "comun.js")
    out = {}
    for pref, ini, fin in (("etq", 'par("etq", {', "});"), ("tasa", 'par("tasa", {', "});")):
        blk = c[c.index(ini) : c.index(fin, c.index(ini))]
        pares = re.findall(r'^\s*(\w+): \["([^"]*)", "([^"]*)"\],', blk, re.M)
        assert pares
        for col, etiqueta, unidad in pares:
            out[f"{pref}.{col}"] = etiqueta
            if unidad:
                out[f"{pref}.{col}.u"] = unidad
    blk = c[c.index("const FLAGS_ES = {") : c.index("};", c.index("const FLAGS_ES = {"))]
    flags = re.findall(r'^\s*(\w+): "([^"]*)",', blk, re.M)
    assert len(flags) >= 30
    out.update({f"flag.{k}": v for k, v in flags})
    for k in RESUMEN_TARJETAS.findall(_leer(SITE / "js" / "inicio.js")):
        out[f"regla.{k}"] = ""
    out["regla.vaca_muerta_petroleo_por_cohorte"] = ""
    return out


def _variables(texto: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", texto))


def test_every_key_has_its_english_and_none_is_left_over():
    en = _en()
    usadas = {**_claves_html(), **_claves_js(), **_claves_dinamicas()}
    assert len(usadas) > 300
    faltan = sorted(set(usadas) - set(en))
    assert not faltan, f"keys with no English in site/js/i18n.js: {faltan}"
    sobran = sorted(set(en) - set(usadas))
    assert not sobran, f"English entries nothing uses: {sobran}"
    assert all(v.strip() for v in en.values())


def test_english_keeps_the_variables_of_the_spanish():
    en = _en()
    for clave, es in _claves_js().items():
        assert _variables(en[clave]) == _variables(es), (
            f"{clave}: {{variables}} differ between Spanish and English"
        )


def test_identifiers_are_not_translated():
    """Column names, table names and ADR numbers appear in the English exactly as in the Spanish."""
    en = _en()
    usadas = {**_claves_html(), **_claves_js()}
    for clave, es in usadas.items():
        assert sorted(re.findall(r"ADR-\d{3}", es)) == sorted(re.findall(r"ADR-\d{3}", en[clave])), clave
        # <code> holding a single identifier (a table, a column, a flag) is kept verbatim; the English may add a gloss
        nombres = set(re.findall(r"<code>([a-z][a-z0-9_]*)</code>", es))
        assert nombres <= set(re.findall(r"<code>([a-z][a-z0-9_]*)</code>", en[clave])), clave
    # the flags and the column labels are keyed by the tables' own names
    from vma import indicadores as I
    from vma import site as S

    for clave in en:
        if clave.startswith("etq."):
            col = clave.split(".")[1]
            assert col in S.POZOS_FROM_INDICADORES + S.POZOS_FROM_MAESTRO or col in I.COLUMNS, clave
        if clave.startswith("tasa."):
            assert clave.split(".")[1] in S.CURVAS_RATES, clave


def test_every_page_has_the_switch_the_early_script_and_the_simulator_link():
    for pagina in PAGINAS:
        s = _leer(SITE / f"{pagina}.html")
        assert '<html lang="es">' in s, pagina  # Spanish is the default and the source language
        cabeza = s[: s.index("</head>")]
        assert '<script src="js/idioma.js"></script>' in cabeza, f"{pagina}: idioma.js must load in <head>"
        assert re.search(r'<title data-i18n="[\w.]+">', cabeza) and 'data-i18n-attr="content:' in cabeza, (
            pagina
        )
        assert 'data-lang="es"' in s and 'data-lang="en"' in s and 'href="?lang=en"' in s, pagina
        nav = s[s.index("<nav>") : s.index("</nav>")]
        assert re.findall(r'href="(\w+)\.html"', nav) == list(PAGINAS), pagina
        assert len(re.findall(r'data-i18n="nav\.\w+"', nav)) == len(PAGINAS), pagina
        assert 'type="module"' in s
    idioma = _leer(SITE / "js" / "idioma.js")
    orden = [idioma.index(x) for x in ('.get("lang")', "window.localStorage", "window.navigator.language")]
    assert orden == sorted(orden)  # ?lang=, then the saved choice, then the browser
    assert idioma.count("try {") >= 2  # the URL and the storage are both guarded
    i18n = _leer(SITE / "js" / "i18n.js")
    assert "try {" in i18n and "localStorage.setItem" in i18n
    assert "import " not in i18n.split("export const LANG")[0]  # dependency-free: Node loads it alone


def test_numbers_follow_the_language():
    for js in sorted((SITE / "js").glob("*.js")):
        src = _leer(js)
        if js.name == "i18n.js":
            assert '"en-US"' in src and '"es-AR"' in src
        else:
            assert "es-AR" not in src and "en-US" not in src, f"{js.name} formats numbers in a fixed locale"
    assert "Intl.NumberFormat(LOCALE" in _leer(SITE / "js" / "comun.js")
    assert "Intl.NumberFormat(LOCALE" in _leer(SITE / "js" / "simulador.js")


def test_home_leads_to_the_simulator():
    s = _leer(SITE / "index.html")
    bloque = s[s.index('class="probar"') : s.index('id="tarjetas"')]
    assert 'href="simulador.html"' in bloque and "inicio.probar.titulo" in bloque
    assert s.index('class="probar"') < s.index('id="tarjetas"')  # near the top, before the headline counts


def test_simulator_says_what_it_is_not_in_both_languages():
    es = _leer(SITE / "simulador.html")
    en = _en()
    ingles = " ".join(v for k, v in en.items() if k.startswith("sim."))
    for frase in (
        "P10 es el caso alto",
        "día efectivo",
        "Sin interferencia entre pozos, sin restricciones de instalaciones, sin costos",
        "bruto",
        "no es ganancia",
        "dispersión entre pozos",
        "extrapolación hiperbólica",
        "no el pronóstico del plan de ninguna operadora",
    ):
        assert frase in es, frase
    for frase in (
        "P10 is the high case",
        "per producing day",
        "No interference between wells, no facility constraints, no costs",
        "gross",
        "not profit",
        "well-to-well dispersion",
        "hyperbolic extrapolation",
        "not a forecast of any operator's plan",
    ):
        assert frase in ingles, frase
    todo = (es + ingles + _leer(SITE / "js" / "simulador.js")).lower()
    assert "digital twin" not in todo and "gemelo digital" not in todo
    # the conversions for an English reader are declared as conversions, and the source units stay
    assert "6.2898" in _leer(ROOT / "docs" / "decisiones.md") and "bbl_por_m3" in _leer(
        SITE / "js" / "simulador.js"
    )
    assert "converted" in en["sim.unidades.campo"] and "source" in en["sim.unidades.metrico"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_t_and_enlace_under_node():
    def correr(*args):
        r = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "js" / "correr_i18n.mjs"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    en = correr("en", "explicito")
    assert (en["lang"], en["locale"]) == ("en", "en-US") and en["n_claves"] == len(_en())
    assert en["simple"] == "Type curves" and en["con_variable"] == "month 12"
    assert en["sin_clave"] == "texto 7 en español"  # no English: the Spanish source, never a bare key
    assert en["variable_ausente"] == "month {m}"
    assert en["numero"] == "1,234,567.8"
    assert en["enlaces"] == [
        "simulador.html?lang=en",
        "metodo.html?lang=en#reglas",
        "curvas.html?x=1&lang=en",
        "https://example.org/a.html",
        "#ancla",
        "index.html?lang=es",
    ]
    es = correr("es")
    assert (es["lang"], es["locale"]) == ("es", "es-AR")
    assert es["simple"] == "Curvas tipo" and es["con_variable"] == "mes 12"
    assert es["numero"] == "1.234.567,8"
    assert es["enlaces"][0] == "simulador.html"  # the language was not chosen in the URL: links stay clean
    assert correr("fr")["lang"] == "es"  # i18n.js only knows es | en; idioma.js maps everything else to en
