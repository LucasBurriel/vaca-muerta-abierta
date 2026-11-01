"""The site stage: JSON generation on tiny synthetic tables, meta, and the contract between the
JavaScript and the published tables (every column the site reads exists and is documented)."""

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from vma import curvas as C
from vma import indicadores as I
from vma import master as M
from vma import site as S

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DOCS = ROOT / "docs"


# --- synthetic tables --------------------------------------------------------------------------------------


def _master(n=4):
    rows = []
    for i in range(n):
        rows.append(
            {
                "sigla": f"OP.Nq.A-{i}(h)",
                "sigla_clave": f"OP.NQ.A-{i}(H)",
                "longitud": -68.5 + i * 0.01 if i != 3 else None,
                "latitud": -38.2,
                "estado": "Extracción Efectiva",
                "tipo_pozo": "Petrolífero",
                "sub_tipo_recurso": "SHALE",
                "primera_produccion": pd.Timestamp("2024-01-01"),
                "ultima_produccion": pd.Timestamp("2026-09-01"),
            }
        )
    m = pd.DataFrame(rows)
    for c in M.COLUMNS:
        if c not in m:
            m[c] = None
    return m[M.COLUMNS]


def _ind(n=4):
    rows = []
    for i in range(n):
        rows.append(
            {
                "sigla": f"OP.Nq.A-{i}(h)",
                "sigla_clave": f"OP.NQ.A-{i}(H)",
                "operadora": "OP A" if i < 3 else "OP B",
                "formacion": "Vaca Muerta",
                "area": "AREA",
                "cuenca": "NEUQUINA",
                "en_alcance": i != 3,
                "cohorte": 2024,
                "ventana": "petroleo",
                "rama_m": 2500.0 if i < 2 else None,
                "rama_normalizable": i < 2,
                "etapas": 40,
                "etapas_por_100m": 1.6 if i < 2 else float("nan"),
                "ip90_petroleo_m3_d": 120.123456,
                "ip90_equivalente_m3_d_por_m": 0.0512345 if i < 2 else None,
                "ip90_petroleo_m3_d_por_m": 0.0412345 if i < 2 else None,
                "gor12_m3_m3": None if i == 2 else 150.0,
                "outlier_ip90_m": False if i < 2 else None,
                "flags": "primer_mes_parcial" if i < 2 else "sin_rama_sin_fractura|outlier_no_evaluado",
                "fecha_descarga": "2026-10-30",
                "version_maestro": "2026-10-31",
            }
        )
    d = pd.DataFrame(rows)
    for c in I.COLUMNS:
        if c not in d:
            d[c] = None
    return d[I.COLUMNS]


def _curvas():
    rows = []
    for inc in (True, False):
        for nivel in S.NIVELES:
            for mes in range(0, 80):
                n = 6 if mes < 70 else 3
                rows.append(
                    {
                        "nivel": nivel,
                        "cohorte": 2024,
                        "formacion": "Vaca Muerta",
                        "ventana": "petroleo" if nivel.endswith("ventana") else None,
                        "operadora": "OP A" if nivel.endswith("operadora") else None,
                        "incluye_outliers": inc,
                        "mes": mes,
                        "n_pozos": n,
                        "n_pozos_por_m": n,
                        "publicable": n >= 5,
                        **{
                            f"{r}_{s}": (1.0 / (mes + 1) if n >= 5 else None)
                            for r in C.RATES + C.RATES_M
                            for s in C.STATS
                        },
                    }
                )
            # a group that never reaches 5 wells must not be shipped
            rows.append(
                {
                    "nivel": nivel,
                    "cohorte": 2010,
                    "formacion": "Lajas",
                    "ventana": None,
                    "operadora": None,
                    "incluye_outliers": inc,
                    "mes": 0,
                    "n_pozos": 2,
                    "n_pozos_por_m": 0,
                    "publicable": False,
                }
            )
    c = pd.DataFrame(rows)
    for col in C.COLUMNS:
        if col not in c:
            c[col] = None
    return c[C.COLUMNS]


MANIFEST = {
    "generated_at": "2026-10-31T00:16:47+00:00",
    "sources": [
        {
            "key": "produccion_nc",
            "file": "produccion_nc.csv",
            "bytes": 10,
            "sha256": "ab" * 32,
            "ckan_last_modified": "2026-10-22",
            "url": "https://example.invalid/x.csv",
            "license": "CC-BY-4.0",
        }
    ],
}


@pytest.fixture
def built(tmp_path):
    meta = S.build_site_data(
        tmp_path, _master(), _ind(), _curvas(), MANIFEST, "2026-10-31", today=date(2026, 10, 31)
    )
    return tmp_path, meta


# --- helpers -----------------------------------------------------------------------------------------------------------


def test_sig_and_clean():
    assert S.sig(0.0512345) == 0.05123
    assert S.sig(1234567.0) == 1234567
    assert S.sig(float("nan")) is None and S.sig(None) is None
    assert S.sig(True) is True and S.sig(7) == 7
    assert S.clean(pd.NaT) is None and S.clean(pd.Timestamp("2024-01-01")) == "2024-01-01"
    assert S.clean(float("inf")) is None


def test_encode_flags():
    names, rows = S.encode_flags(pd.Series(["a|b", "", None, "b"]))
    assert names == ["a", "b"] and rows == [[0, 1], [], [], [1]]


# --- generated files ---------------------------------------------------------------------------------------------


def test_files_written_and_valid_json(built):
    out, meta = built
    expected = {"pozos.json", "resumen.json", "meta.json"} | {f"curvas_{n}.json" for n in S.NIVELES}
    assert {p.name for p in out.glob("*.json")} == expected
    for p in out.glob("*.json"):
        text = p.read_text(encoding="utf-8")
        assert "NaN" not in text and "Infinity" not in text
        json.loads(text)
    assert set(meta["archivos"]) == expected
    assert meta["archivos"]["pozos.json"] == len((out / "pozos.json").read_bytes())


def test_pozos_json_is_columnar_with_origin_and_flags(built):
    out, _ = built
    P = json.loads((out / "pozos.json").read_text(encoding="utf-8"))
    assert P["n"] == 4
    cols = P["columnas"]
    assert set(S.POZOS_FROM_INDICADORES) | set(S.POZOS_FROM_MAESTRO) == set(cols)
    assert all(len(v) == 4 for v in cols.values())
    assert P["origen"]["longitud"] == "pozos.longitud" and P["origen"]["rama_m"] == "indicadores.rama_m"
    i = cols["sigla_clave"].index("OP.NQ.A-2(H)")
    assert cols["rama_m"][i] is None and cols["etapas_por_100m"][i] is None  # NaN -> null, never 0
    assert [P["flags_dic"][j] for j in cols["flags"][i]] == ["sin_rama_sin_fractura", "outlier_no_evaluado"]
    assert cols["ip90_equivalente_m3_d_por_m"][0] == 0.05123  # 4 significant digits
    assert cols["longitud"][0] == -68.5 and cols["longitud"][3] is None
    assert cols["primera_produccion"][0] == "2024-01-01"


def test_curvas_json_cut_at_mes_max_and_only_publishable_groups(built):
    out, _ = built
    for nivel in S.NIVELES:
        D = json.loads((out / f"curvas_{nivel}.json").read_text(encoding="utf-8"))
        assert D["nivel"] == nivel and D["tabla"] == "curvas_tipo" and D["mes_max"] == S.MES_MAX
        assert D["n_grupos"] == 2 and {g["incluye_outliers"] for g in D["grupos"]} == {True, False}
        assert all(
            g["formacion"] == "Vaca Muerta" for g in D["grupos"]
        )  # the 2-well Lajas group is not shipped
        g = D["grupos"][0]
        assert g["mes"] == list(range(0, S.MES_MAX + 1)) and len(g["n_pozos"]) == S.MES_MAX + 1
        assert set(g["series"]) == set(S.CURVAS_RATES) and set(g["series"]["petroleo_m3_d"]) == {
            "p10",
            "p50",
            "p90",
        }
        assert g["series"]["petroleo_m3_d"]["p50"][0] == 1.0
        assert "día efectivo" in D["nota"]


def test_curvas_json_keeps_low_n_months_as_nulls(tmp_path):
    c = _curvas()
    c.loc[(c.mes == 10), ["publicable"]] = False
    c.loc[(c.mes == 10), [f"{r}_{s}" for r in C.RATES + C.RATES_M for s in C.STATS]] = None
    c.loc[(c.mes == 10), ["n_pozos", "n_pozos_por_m"]] = 4
    D = S.build_curvas(c, "cohorte_formacion", mes_max=20)
    g = D["grupos"][0]
    assert (
        g["n_pozos"][10] == 4
        and g["publicable"][10] is False
        and g["series"]["petroleo_m3_d"]["p50"][10] is None
    )


def test_resumen_cites_table_and_column(built):
    out, _ = built
    R = json.loads((out / "resumen.json").read_text(encoding="utf-8"))
    assert (
        R["pozos_maestro"]["valor"] == 4
        and R["pozos_en_alcance"]["valor"] == 3
        and R["pozos_con_rama"]["valor"] == 2
    )
    for k, v in R.items():
        if k in ("grupos_curvas_publicables", "ventanas"):
            assert all({"valor", "tabla", "columna", "regla"} <= set(x) for x in v.values())
        elif k == "vaca_muerta_petroleo_por_cohorte":
            assert (
                v["tabla"] == "indicadores" and v["filas"][0]["cohorte"] == 2024 and v["filas"][0]["n"] == 3
            )
        else:
            assert {"valor", "tabla", "columna", "regla"} <= set(v), k
    assert R["grupos_curvas_publicables"]["cohorte_formacion"]["valor"] == 1
    assert R["ultima_produccion"]["valor"] == "2026-09-01"


def test_meta_has_dates_version_and_manifest_hashes(built):
    out, meta = built
    M_ = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert (
        M_["fecha_descarga"] == "2026-10-30"
        and M_["version_maestro"] == "2026-10-31"
        and M_["fecha_generacion"] == "2026-10-31"
    )
    assert M_["fuentes"][0]["sha256"] == "ab" * 32 and M_["fuentes"][0]["key"] == "produccion_nc"
    assert M_["tablas"]["indicadores"]["filas"] == 4 and M_["tablas"]["curvas_tipo"]["columnas"] == len(
        C.COLUMNS
    )
    assert M_["archivos"] == meta["archivos"] and "meta.json" in M_["archivos"]
    assert "CC-BY" in M_["licencia_datos"]


# --- the contract between the JavaScript and the published tables -------------------------------------------------------


def _documented_columns(md: Path) -> set[str]:
    """Backticked column names in a docs table, with the `{N}` and `*` patterns of docs/indicadores.md expanded."""
    text = md.read_text(encoding="utf-8")
    found: set[str] = set()
    for tok in re.findall(r"`([a-zA-Z0-9_{}*]+)`", text):
        if "{" in tok and "{N}" not in tok:
            continue
        variants = [tok]
        if "{N}" in tok:
            ns = (30, 90, 180) if tok.startswith("ip") else (6, 12, 24)
            variants = [tok.replace("{N}", str(n)) for n in ns]
        out = []
        for v in variants:
            if "*" in v:
                fluids = ("petroleo_m3", "gas_mil_m3", "equivalente_m3", "agua_m3")
                out += [v.replace("*", f + d) for f in fluids for d in ("", "_d")]
            else:
                out.append(v)
        found.update(out)
    return found


def test_site_columns_exist_in_tables_and_docs():
    ind_doc = _documented_columns(DOCS / "indicadores.md")
    mas_doc = _documented_columns(DOCS / "maestro.md")
    for c in S.POZOS_FROM_INDICADORES:
        assert c in I.COLUMNS, c
        assert c in ind_doc, f"{c} not documented in docs/indicadores.md"
    for c in S.POZOS_FROM_MAESTRO:
        assert c in M.COLUMNS, c
        assert c in mas_doc, f"{c} not documented in docs/maestro.md"
    for c in S.CURVAS_COLUMNS:
        assert c in C.COLUMNS, c
        assert c in ind_doc, f"{c} not documented in docs/indicadores.md"


def _js_sources() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in list(SITE.glob("js/*.js")) + list(SITE.glob("*.html"))
    )


def test_js_reads_only_columns_the_site_data_has():
    """Every `columnas.<name>`, `c.<name>[i]` access and `cita("<table>", "<column>")` in the JS names a real column."""
    src = _js_sources()
    pozos_cols = set(S.POZOS_FROM_INDICADORES) | set(S.POZOS_FROM_MAESTRO)
    used = set(re.findall(r"\bcolumnas\.([a-z_][a-z0-9_]*)", src)) | set(
        re.findall(r"\bc\.([a-z_][a-z0-9_]*)\[i\]", src)
    )
    unknown = used - pozos_cols
    assert not unknown, f"JS reads columns pozos.json does not carry: {sorted(unknown)}"
    tables = {"pozos": set(M.COLUMNS), "indicadores": set(I.COLUMNS), "curvas_tipo": set(C.COLUMNS)}
    for tabla, col in re.findall(r'cita\("(\w+)",\s*"([a-z0-9_]+)"', src):
        assert tabla in tables, tabla
        assert col in tables[tabla], f"cita({tabla}, {col}) names a column the table does not have"
    # dynamic citations in curvas.js: `${tasa}_p50` etc. over the rate selector
    for rate in S.CURVAS_RATES:
        for s in ("p10", "p50", "p90"):
            assert f"{rate}_{s}" in C.COLUMNS
    # the explorer's and the map's column lists / option values
    for col in re.findall(r'\["([a-z0-9_]+)", "(?:indicadores|pozos)", (?:\d+|null)\]', src):
        assert col in pozos_cols, col
    for col in re.findall(r'<option value="([a-z0-9_]+)">', (SITE / "mapa.html").read_text(encoding="utf-8")):
        assert col in pozos_cols, col


def test_site_pages_exist_and_pin_cdn_versions():
    for page in ("index", "explorador", "curvas", "mapa", "metodo"):
        assert (SITE / f"{page}.html").exists()
    src = _js_sources()
    for url in re.findall(r'src="(https://[^"]+)"', src) + re.findall(r'href="(https://cdnjs[^"]+)"', src):
        assert re.search(r"/\d+\.\d+\.\d+/", url), f"CDN URL without a pinned version: {url}"
    assert "integrity=" in src
    assert "día efectivo" in (SITE / "curvas.html").read_text(encoding="utf-8")
    assert (
        SITE / "data" / "meta.json"
    ).exists() or True  # data is generated by `pipeline.py site`, not required for tests
