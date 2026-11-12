"""Phase 3: the static site's data files.

The site (``site/``) is plain HTML + ES modules with no build step; it reads **pre-aggregated JSON**
written by ``python pipeline.py site`` into ``site/data/`` (ADR-021, ADR-022). Nothing in here is a
new indicator: every number is copied from the published tables of the latest
``data/publicado/<date>/`` folder, rounded for transport, and every JSON carries the name of the
table and column it came from, so the page can print "tabla.columna" next to each value
("sin cita no hay número").

Files written:

- ``meta.json``      download date, master version, last production month, manifest hashes, sizes.
- ``resumen.json``   the headline counts of the home page, each with its table and column.
- ``pozos.json``     one entry per master well (columnar), the explorer's and the map's table.
- ``curvas_<nivel>.json``  type curves per level, groups with at least one publishable month, ``mes <= MES_MAX``
  (ADR-023), P10/P50/P90 and ``n_pozos`` per month.
- ``simulador.json``  what the browser campaign simulator samples (ADR-036): per cohort × formation × window
  group, the oil and gas P10/P50/P90 curves (absolute and per metre) already extended to ``SIM_MESES`` months by
  the same function the Python simulator uses, plus the default public prices. The one file that is not a plain
  copy of published values: months beyond ``ultimo_mes`` are a hyperbolic extrapolation and are counted as such.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

MES_MAX = 60  # ADR-023: the site plots five years of type curve; the tables keep every month
SIG = 4  # significant digits kept for transport; the published Parquet keeps full precision
COORD_DECIMALS = 5  # ~1 m

# Columns copied into pozos.json, by source table (docs/indicadores.md, docs/maestro.md).
POZOS_FROM_INDICADORES = [
    "sigla",
    "sigla_clave",
    "operadora",
    "formacion",
    "area",
    "cuenca",
    "en_alcance",
    "cohorte",
    "ventana",
    "rama_m",
    "rama_normalizable",
    "etapas",
    "etapas_por_100m",
    "arena_tn_por_m",
    "agua_fractura_m3_por_m",
    "dias_efectivos_total",
    "ip90_petroleo_m3_d",
    "ip90_gas_mil_m3_d",
    "ip90_equivalente_m3_d",
    "ip90_petroleo_m3_d_por_m",
    "ip90_gas_mil_m3_d_por_m",
    "ip90_equivalente_m3_d_por_m",
    "acum12_petroleo_m3_por_m",
    "acum12_gas_mil_m3_por_m",
    "acum12_equivalente_m3_por_m",
    "gor12_m3_m3",
    "corte_agua12",
    "outlier_ip90_m",
    "flags",
]
POZOS_FROM_MAESTRO = ["longitud", "latitud", "estado", "tipo_pozo", "sub_tipo_recurso", "primera_produccion"]

CURVAS_KEYS = ["cohorte", "formacion", "ventana", "operadora", "incluye_outliers"]
CURVAS_RATES = [
    "petroleo_m3_d",
    "gas_mil_m3_d",
    "equivalente_m3_d",
    "petroleo_m3_d_por_m",
    "gas_mil_m3_d_por_m",
    "equivalente_m3_d_por_m",
]
CURVAS_STATS = ["p10", "p50", "p90"]
CURVAS_COLUMNS = (
    ["nivel", *CURVAS_KEYS, "mes", "n_pozos", "n_pozos_por_m", "publicable"]
    + [f"{r}_{s}" for r in CURVAS_RATES for s in CURVAS_STATS]
    + ["fecha_descarga", "version_maestro"]
)
NIVELES = ["cohorte_formacion", "cohorte_formacion_ventana", "cohorte_formacion_operadora"]

# simulador.json (ADR-036)
SIM_MESES = 120  # horizon of the browser simulator: ten years
SIM_NIVEL = "cohorte_formacion_ventana"
SIM_CURVAS = ["petroleo_m3_d", "gas_mil_m3_d", "petroleo_m3_d_por_m", "gas_mil_m3_d_por_m"]
SIM_MAX_BYTES = 1_500_000
SIM_REGION_PETROLEO = "Neuquén"  # the defaults of the valuation (ADR-034)
SIM_REGION_GAS = "Neuquina"
SIM_SEGMENTO_GAS = "ppp"
SIM_CONTRATO_GAS = "total"


# --- scalar helpers -------------------------------------------------------------------------------


def sig(x, digits: int = SIG):
    """Round to ``digits`` significant digits; None for null/NaN/inf. Ints stay ints."""
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    try:
        f = float(x)
    except (TypeError, ValueError):
        return x
    if math.isnan(f) or math.isinf(f):
        return None
    if f == 0:
        return 0.0
    if float(f).is_integer() and abs(f) < 1e15:
        return int(f)
    return float(f"{f:.{digits}g}")


def clean(x):
    """A JSON-safe scalar: None for NaN/NaT, ISO for dates, Python ints/floats/bools/str otherwise."""
    if x is None:
        return None
    if isinstance(x, (pd.Timestamp, datetime, date)):
        return None if pd.isna(x) else pd.Timestamp(x).strftime("%Y-%m-%d")
    if isinstance(x, (bool,)):
        return x
    if hasattr(x, "item"):  # numpy scalar
        x = x.item()
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, str):
        return x
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return x


def column(series: pd.Series, *, digits: int | None = SIG) -> list:
    out = []
    for v in series.tolist():
        v = clean(v)
        if digits is not None and isinstance(v, float):
            v = sig(v, digits)
        out.append(v)
    return out


# --- pozos.json -----------------------------------------------------------------------------------


def encode_flags(flags: pd.Series, sep: str = "|") -> tuple[list[str], list[list[int]]]:
    """``'a|b'`` per row -> a dictionary of flag names and, per row, the indices into it."""
    names: dict[str, int] = {}
    rows: list[list[int]] = []
    for f in flags.fillna("").tolist():
        idx = []
        for name in str(f).split(sep):
            if not name:
                continue
            if name not in names:
                names[name] = len(names)
            idx.append(names[name])
        rows.append(idx)
    return list(names), rows


def build_pozos(ind: pd.DataFrame, master: pd.DataFrame) -> dict:
    """Columnar table for the explorer and the map: indicators + master coordinates, one entry per well."""
    m = master.set_index("sigla_clave")[POZOS_FROM_MAESTRO]
    t = ind[POZOS_FROM_INDICADORES].merge(m, left_on="sigla_clave", right_index=True, how="left")
    t = t.sort_values("sigla_clave").reset_index(drop=True)
    flag_names, flag_rows = encode_flags(t["flags"])
    columnas: dict[str, list] = {}
    for c in POZOS_FROM_INDICADORES:
        if c == "flags":
            continue
        columnas[c] = column(t[c])
    for c in POZOS_FROM_MAESTRO:
        digits = COORD_DECIMALS if c in ("longitud", "latitud") else SIG
        vals = column(t[c], digits=None)
        if c in ("longitud", "latitud"):
            vals = [None if v is None else round(float(v), digits) for v in vals]
        columnas[c] = vals
    columnas["flags"] = flag_rows
    origen = {c: f"indicadores.{c}" for c in POZOS_FROM_INDICADORES}
    origen.update({c: f"pozos.{c}" for c in POZOS_FROM_MAESTRO})
    return {
        "tabla": "indicadores + pozos (join sigla_clave)",
        "origen": origen,
        "n": int(len(t)),
        "flags_dic": flag_names,
        "columnas": columnas,
    }


# --- curvas_<nivel>.json ---------------------------------------------------------------------------


def build_curvas(curvas: pd.DataFrame, nivel: str, mes_max: int = MES_MAX) -> dict:
    """Groups of one level with at least one publishable month, months 0..mes_max, columnar per group."""
    c = curvas[(curvas.nivel == nivel) & (curvas.mes <= mes_max)]
    grupos = []
    for key, g in c.groupby(CURVAS_KEYS, dropna=False, sort=True):
        if not bool(g.publicable.any()):
            continue
        g = g.sort_values("mes")
        series = {
            r: {s: column(g[f"{r}_{s}"]) for s in CURVAS_STATS}
            for r in CURVAS_RATES
            if g[f"{r}_p50"].notna().any()
        }
        grupo = {k: clean(v) for k, v in zip(CURVAS_KEYS, key, strict=True)}
        grupo.update(
            {
                "mes": column(g["mes"]),
                "n_pozos": column(g["n_pozos"]),
                "n_pozos_por_m": column(g["n_pozos_por_m"]),
                "publicable": column(g["publicable"]),
                "series": series,
            }
        )
        grupos.append(grupo)
    return {
        "tabla": "curvas_tipo",
        "nivel": nivel,
        "mes_max": mes_max,
        "estadisticos": CURVAS_STATS,
        "tasas": CURVAS_RATES,
        "nota": "tasas por día efectivo de producción (tef), no por día calendario (ADR-016)",
        "n_grupos": len(grupos),
        "grupos": grupos,
    }


# --- simulador.json --------------------------------------------------------------------------------


def _precio_ultimo(t: pd.DataFrame, columna: str) -> tuple[dict, pd.Series] | None:
    t = t[t.precio_dataset.notna()]
    if not len(t):
        return None
    f = t.sort_values(["anio", "mes"]).iloc[-1]
    return {
        "region": clean(f.region),
        "mes": f"{int(f.anio):04d}-{int(f.mes):02d}",
        "provisorio": bool(f.provisorio),
        "segmento": clean(f.segmento),
        "contrato": clean(f.contrato),
        "fuente": clean(f.fuente),
        "unidad_dataset": clean(f.unidad_dataset),
        "precio_dataset": sig(float(f.precio_dataset), 5),
        "tabla": "precios",
        "columna": columna,
    }, f


def precios_simulador(precios: pd.DataFrame | None) -> dict | None:
    """The latest public price of each product in the default regions, in the units ``valorizar.py`` uses
    (USD/m³ and USD per mil m³) and in the ones a reader types (USD/bbl, USD/MMBTU). None without a prices table."""
    from vma import units

    if precios is None or not len(precios):
        return None
    out: dict = {
        "petroleo": None,
        "gas": None,
        "fecha_realizacion": None,
        "fecha_descarga": clean(precios.fecha_descarga.iloc[0]),
        "regla": "último mes publicado de cada producto en la región por defecto (ADR-034, ADR-035)",
        "licencia": "CC-BY 4.0, Secretaría de Energía de la Nación Argentina",
    }
    pe = _precio_ultimo(
        precios[(precios.producto == "petroleo") & (precios.region == SIM_REGION_PETROLEO)], "precio_usd_m3"
    )
    if pe:
        d, f = pe
        d["usd_m3"] = sig(float(f.precio_usd_m3), 5)
        d["usd_bbl"] = sig(float(f.precio_usd_m3) / units.BBL_PER_M3, 5)
        out["petroleo"] = d
        out["fecha_realizacion"] = clean(f.fecha_realizacion)
    ga = _precio_ultimo(
        precios[
            (precios.producto == "gas")
            & (precios.region == SIM_REGION_GAS)
            & (precios.segmento == SIM_SEGMENTO_GAS)
            & (precios.contrato == SIM_CONTRATO_GAS)
        ],
        "precio_usd_mil_m3",
    )
    if ga:
        d, f = ga
        d["usd_mmbtu"] = sig(float(f.precio_dataset), 5)
        d["usd_mil_m3"] = sig(float(f.precio_usd_mil_m3), 5)
        out["gas"] = d
    return out if (out["petroleo"] or out["gas"]) else None


def build_simulador(
    curvas: pd.DataFrame, precios: pd.DataFrame | None = None, meses: int = SIM_MESES
) -> dict:
    """What the browser Monte Carlo samples (ADR-036): for every cohort × formation × window group without
    outliers, the P10/P50/P90 of oil and gas (absolute and per metre where published) extended to ``meses`` months
    with ``vma.simulacion.campania.cuantiles_extendidos``, the function the Python simulator itself uses. A curve
    with fewer than ``MIN_PUNTOS`` usable months is left out; a group with no curve left is dropped."""
    from vma import units
    from vma.simulacion import campania as SC
    from vma.simulacion import declinacion as DC

    c = curvas[(curvas.nivel == SIM_NIVEL) & curvas.incluye_outliers.eq(False)]
    grupos = []
    for key, g in c.groupby(["cohorte", "formacion", "ventana"], dropna=True, sort=True):
        g = g.sort_values("mes")
        series: dict[str, dict] = {}
        for col in SIM_CURVAS:
            if f"{col}_p50" not in g:
                continue
            n_col = "n_pozos_por_m" if col.endswith("_por_m") else "n_pozos"
            cu = g[["mes", f"{col}_p10", f"{col}_p50", f"{col}_p90", n_col]].set_axis(
                ["mes", "p10", "p50", "p90", "n"], axis=1
            )
            n_mes = g.set_index("mes")[n_col]
            try:
                e = SC.cuantiles_extendidos(cu, meses)
            except SC.ErrorSimulacion:
                continue
            validos = [bool(v) for v in e["valido"]]
            if sum(validos) < DC.MIN_PUNTOS:  # e.g. an old cohort published only beyond the horizon
                continue
            largo = max(i for i, v in enumerate(validos) if v) + 1
            series[col] = {
                **{
                    s: [sig(float(e[s][i])) if validos[i] else None for i in range(largo)]
                    for s in CURVAS_STATS
                },
                "publicados": int(sum(validos[: min(e["ultimo_mes"], meses - 1) + 1])),  # within the horizon
                "ultimo_mes": min(e["ultimo_mes"], meses - 1),
                "validos": int(sum(validos)),
                "acotados": e["meses_acotados"],
                "descartados": e[
                    "meses_descartados"
                ],  # published months after the splice, not sampled (ADR-038)
                # wells behind the splice month: the level the extrapolated tail starts from
                "n_ultimo": clean(n_mes.get(e["ultimo_mes"])),
            }
        if not series:
            continue
        cohorte, formacion, ventana = key
        grupos.append(
            {
                "cohorte": int(cohorte),
                "formacion": clean(formacion),
                "ventana": clean(ventana),
                "n_pozos": clean(g["n_pozos"].iloc[0]),
                "n_pozos_por_m": clean(g["n_pozos_por_m"].iloc[0]),
                "curvas": series,
            }
        )
    return {
        "tabla": "curvas_tipo",
        "nivel": SIM_NIVEL,
        "incluye_outliers": False,
        "meses": meses,
        "estadisticos": CURVAS_STATS,
        "tasas": SIM_CURVAS,
        "min_puntos": DC.MIN_PUNTOS,
        "d_min_anual": DC.D_MIN_ANUAL,
        "dias_mes": SC.DIAS_MES,
        "jitter_percentil": 8.0,
        "uptime": 0.92,
        "bbl_por_m3": units.BBL_PER_M3,
        "ft3_por_m3": units.FT3_PER_M3,
        "mmbtu_por_mil_m3": units.MMBTU_PER_THOUSAND_M3,
        "nota": (
            "tasas por día efectivo de producción (ADR-016); hasta ultimo_mes son los P10/P50/P90 publicados "
            "(curvas_tipo), después una extrapolación hiperbólica de cada cuantil empalmada al último valor, con "
            "declinación terminal d_min_anual y las colas ordenadas (ADR-031, ADR-036)"
        ),
        "precios": precios_simulador(precios),
        "n_grupos": len(grupos),
        "grupos": grupos,
    }


# --- resumen.json -----------------------------------------------------------------------------------


def _cita(valor, tabla: str, columna: str, regla: str) -> dict:
    return {
        "valor": sig(valor) if not isinstance(valor, str) else valor,
        "tabla": tabla,
        "columna": columna,
        "regla": regla,
    }


def build_resumen(ind: pd.DataFrame, master: pd.DataFrame, curvas: pd.DataFrame) -> dict:
    """Headline counts for the home page. Every entry says which table, column and rule produced it."""
    scope = ind[ind.en_alcance.eq(True)]
    prod = scope[scope.cohorte.notna()]
    con_rama = scope[scope.rama_normalizable.eq(True)]
    con_ip90m = prod[prod.ip90_equivalente_m3_d_por_m.notna()]
    screened = scope[scope.outlier_ip90_m.notna()]
    out = screened[screened.outlier_ip90_m.eq(True)]
    ult = master.ultima_produccion.max() if "ultima_produccion" in master else None
    pub = curvas[curvas.publicable.eq(True) & (curvas.mes == 0) & curvas.incluye_outliers.eq(True)]
    por_nivel = pub.groupby("nivel").size().to_dict() if len(pub) else {}
    r = {
        "pozos_maestro": _cita(
            len(master), "pozos", "sigla_clave", "una fila por pozo físico (ADR-003, ADR-011)"
        ),
        "pozos_en_alcance": _cita(
            len(scope),
            "indicadores",
            "en_alcance",
            "cuenca = NEUQUINA y tipo_recurso = NO CONVENCIONAL (ADR-002)",
        ),
        "pozos_productores": _cita(
            len(prod), "indicadores", "cohorte", "en alcance con primera_produccion (ADR-013)"
        ),
        "pozos_con_rama": _cita(
            len(con_rama),
            "indicadores",
            "rama_normalizable",
            "en alcance, rama_m conocida y >= 500 m (ADR-019)",
        ),
        "pozos_con_ip90_por_m": _cita(
            len(con_ip90m), "indicadores", "ip90_equivalente_m3_d_por_m", "no nulo (ADR-016, ADR-019)"
        ),
        "pozos_evaluados_outlier": _cita(len(screened), "indicadores", "outlier_ip90_m", "no nulo (ADR-018)"),
        "outliers": _cita(len(out), "indicadores", "outlier_ip90_m", "= True (ADR-018)"),
        "operadoras": _cita(
            int(scope.operadora.nunique()),
            "indicadores",
            "operadora",
            "distintas, en alcance (alias/operadoras.csv, ADR-012)",
        ),
        "formaciones": _cita(
            int(scope.formacion.nunique()), "indicadores", "formacion", "distintas, en alcance"
        ),
        "cohorte_min": _cita(
            int(prod.cohorte.min()) if len(prod) else None, "indicadores", "cohorte", "mínimo"
        ),
        "cohorte_max": _cita(
            int(prod.cohorte.max()) if len(prod) else None, "indicadores", "cohorte", "máximo"
        ),
        "ultima_produccion": _cita(clean(ult), "pozos", "ultima_produccion", "máximo"),
        "grupos_curvas_publicables": {
            nivel: _cita(
                int(por_nivel.get(nivel, 0)),
                "curvas_tipo",
                "publicable",
                "mes 0, incluye_outliers, n_pozos >= 5 (ADR-017)",
            )
            for nivel in NIVELES
        },
        "ventanas": {
            str(k): _cita(int(v), "indicadores", "ventana", "en alcance con producción (ADR-020)")
            for k, v in prod.ventana.fillna("sin_gor").value_counts().items()
        },
    }
    # Vaca Muerta by cohort, oil window: median lateral and median IP90 oil per metre (the F2 headline).
    vm = prod[(prod.formacion == "Vaca Muerta") & (prod.ventana == "petroleo")]
    filas = []
    for coh, g in vm.groupby("cohorte"):
        filas.append(
            {
                "cohorte": int(coh),
                "n": int(len(g)),
                "rama_m_mediana": sig(g.rama_m.median()),
                "ip90_petroleo_m3_d_por_m_mediana": sig(g.ip90_petroleo_m3_d_por_m.median()),
                "n_con_ip90_por_m": int(g.ip90_petroleo_m3_d_por_m.notna().sum()),
            }
        )
    r["vaca_muerta_petroleo_por_cohorte"] = {
        "tabla": "indicadores",
        "origen_columnas": ["cohorte", "rama_m", "ip90_petroleo_m3_d_por_m"],
        "regla": "en alcance, formacion = Vaca Muerta, ventana = petroleo; medianas por cohorte",
        "filas": filas,
    }
    return r


# --- meta.json + writer -------------------------------------------------------------------------------


def build_meta(
    manifest: dict,
    version_maestro: str,
    fecha_descarga: str | None,
    tablas: dict[str, tuple[int, int]],
    archivos: dict[str, int],
    today: date,
) -> dict:
    fuentes = [
        {k: s.get(k) for k in ("key", "file", "bytes", "sha256", "ckan_last_modified", "url", "license")}
        for s in manifest.get("sources", [])
    ]
    return {
        "fecha_generacion": today.isoformat(),
        "generado_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fecha_descarga": fecha_descarga,
        "version_maestro": version_maestro,
        "manifest_generated_at": manifest.get("generated_at"),
        "fuentes": fuentes,
        "tablas": {k: {"filas": n, "columnas": c} for k, (n, c) in tablas.items()},
        "archivos": archivos,
        "mes_max_curvas": MES_MAX,
        "licencia_datos": "CC-BY 4.0, Secretaría de Energía de la Nación Argentina",
        "licencia_codigo": "MIT",
    }


def _dump(path: Path, obj) -> int:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def build_site_data(
    out_dir: Path,
    master: pd.DataFrame,
    ind: pd.DataFrame,
    curvas: pd.DataFrame,
    manifest: dict,
    version_maestro: str,
    today: date | None = None,
    mes_max: int = MES_MAX,
    precios: pd.DataFrame | None = None,
) -> dict:
    """Write every JSON the site needs into ``out_dir`` and return the meta dict. ``precios`` (F6) is optional:
    when given, its snapshot is written too; when not, an existing ``precios.json`` is left as it is."""
    from vma.precios.fuentes import snapshot_json

    today = today or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    archivos: dict[str, int] = {}
    archivos["pozos.json"] = _dump(out_dir / "pozos.json", build_pozos(ind, master))
    if precios is not None:
        archivos["precios.json"] = _dump(out_dir / "precios.json", snapshot_json(precios))
    for nivel in NIVELES:
        archivos[f"curvas_{nivel}.json"] = _dump(
            out_dir / f"curvas_{nivel}.json", build_curvas(curvas, nivel, mes_max)
        )
    precios_sim = precios
    if precios_sim is None and (out_dir / "precios.json").exists():  # the committed snapshot (ADR-034)
        from vma.precios.fuentes import desde_json

        precios_sim = desde_json(json.loads((out_dir / "precios.json").read_text(encoding="utf-8")))
    archivos["simulador.json"] = _dump(out_dir / "simulador.json", build_simulador(curvas, precios_sim))
    archivos["resumen.json"] = _dump(out_dir / "resumen.json", build_resumen(ind, master, curvas))
    fecha_descarga = clean(ind.fecha_descarga.iloc[0]) if len(ind) and "fecha_descarga" in ind else None
    tablas = {
        "pozos": (len(master), len(master.columns)),
        "indicadores": (len(ind), len(ind.columns)),
        "curvas_tipo": (len(curvas), len(curvas.columns)),
    }
    if precios is not None:  # the simulator cites it; the snapshot alone does not know the table's size
        tablas["precios"] = (len(precios), len(precios.columns))
    meta = build_meta(manifest, version_maestro, fecha_descarga, tablas, archivos, today)
    archivos["meta.json"] = _dump(out_dir / "meta.json", meta)
    meta["archivos"] = archivos
    _dump(out_dir / "meta.json", meta)
    return meta


def _manifest_de_las_tablas(root: Path, ultimo: Path) -> dict:
    """The manifest the method page shows: the newest download that carries the production file the tables are
    built from. An opt-in download made later (``download regalias_crudo precios_gas`` writes its own dated folder
    with only those two files) must not replace it; without any such folder, the newest manifest as before."""
    dias = sorted((p for p in ultimo.parent.iterdir() if p.is_dir()), reverse=True)
    for dia in dias:
        ruta = dia / "manifest.json"
        if not ruta.exists():
            continue
        m = json.loads(ruta.read_text(encoding="utf-8"))
        if any(s.get("key") == "produccion_nc" for s in m.get("sources", [])):
            return m
    ruta = ultimo / "manifest.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def run(root: Path, today: date | None = None) -> Path:
    """``python pipeline.py site``: read the latest published tables and the raw manifest, write site/data/."""
    from .indicadores import latest_published_dir, latest_raw_dir

    pub = latest_published_dir(root)
    for name in ("indicadores.parquet", "curvas_tipo.parquet"):
        if not (pub / name).exists():
            raise SystemExit(f"{pub / name} missing: run `python pipeline.py indicadores` and `curvas`")
    master = pd.read_parquet(pub / "pozos.parquet")
    ind = pd.read_parquet(pub / "indicadores.parquet")
    curvas = pd.read_parquet(pub / "curvas_tipo.parquet")
    precios = pd.read_parquet(pub / "precios.parquet") if (pub / "precios.parquet").exists() else None
    manifest = _manifest_de_las_tablas(root, latest_raw_dir(root))
    out_dir = root / "site" / "data"
    meta = build_site_data(out_dir, master, ind, curvas, manifest, pub.name, today, precios=precios)
    total = sum(meta["archivos"].values())
    print(f"site data -> {out_dir}  ({total / 1e6:.2f} MB in {len(meta['archivos'])} files)")
    for k, v in meta["archivos"].items():
        print(f"  {k:40} {v / 1e6:6.2f} MB")
    return out_dir


__all__ = [
    "CURVAS_COLUMNS",
    "CURVAS_RATES",
    "MES_MAX",
    "NIVELES",
    "SIM_CURVAS",
    "SIM_MAX_BYTES",
    "SIM_MESES",
    "POZOS_FROM_INDICADORES",
    "POZOS_FROM_MAESTRO",
    "build_curvas",
    "build_meta",
    "build_pozos",
    "build_resumen",
    "build_simulador",
    "build_site_data",
    "encode_flags",
    "precios_simulador",
    "run",
    "sig",
]
