"""Phase 1: the well master. One row per physical well.

A physical well is a sigla at normalisation level L2 (``trim + upper + single spaces``,
ADR-003); that key is ``sigla_clave`` and the published ``sigla`` is the register's own
spelling (trimmed). Every ``idpozo`` is a well × productive formation and is kept as a
member of its physical well. The universe is every ``idpozo`` that appears in the unconventional
production file or in the fracture file (ADR-011); the register (``pozos``), the padrón
of first production and the operators' listing enrich it.

Each derived column has one rule, written in ``docs/maestro.md`` and applied here; every
row carries ``flags`` (which rules fired, what was missing) and ``linaje`` (which source
fed each group of columns). Units are the published ones (m³, thousands of m³, tonnes,
metres); the barrel/Mcf columns go through ``vma/units.py`` and nowhere else (ADR-004).

Published as ``data/publicado/<date>/pozos.csv`` and ``pozos.parquet`` (ADR-014) plus a
dated report ``informes/maestro-<date>.md`` with charts in ``docs/maestro-*.png``.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from . import units
from .alias import Aliases, load_aliases, update_siglas, write_alias
from .download import latest_raw_dir
from .normalize import sigla_l2
from .quality import BLUE, GRID, INK, MUTED, ORANGE, SURFACE, connect_raw, df, md_table

SEP = "|"
PLACEHOLDER_BEFORE = date(1950, 1, 1)  # ADR-013: dates before this are placeholders (1900/1902/1910-01-01)
DEPTH_MAX_M = 8000.0
MIN_STAGES_HORIZONTAL = 10  # ADR-010: lateral = 0 with >= 10 stages is a missing length, not a vertical well
ARGENTINA_BBOX = (-74.0, -53.0, -56.0, -21.0)  # lon_min, lon_max, lat_min, lat_max
BASIN_BBOX = {
    "NEUQUINA": (-71.5, -65.5, -41.5, -33.5),
    "GOLFO SAN JORGE": (-71.0, -65.0, -48.5, -43.5),
    "AUSTRAL": (-73.5, -63.5, -55.5, -48.5),
    "NOROESTE": (-66.5, -61.5, -26.5, -21.5),
    "CUYANA": (-70.5, -66.5, -36.0, -31.0),
}
_COORD = re.compile(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]")

COLUMNS = [
    "sigla",
    "sigla_clave",
    "alias_sigla",
    "idpozos",
    "n_idpozo",
    "idpozo_principal",
    "nombre_propio",
    "operadora",
    "operadoras_historicas",
    "formacion_principal",
    "formaciones",
    "area",
    "yacimiento",
    "cuenca",
    "provincia",
    "tipo_recurso",
    "sub_tipo_recurso",
    "tipo_pozo",
    "clasificacion",
    "estado",
    "longitud",
    "latitud",
    "cota_m",
    "profundidad_m",
    "fecha_inicio_perforacion",
    "fecha_fin_perforacion",
    "fecha_inicio_terminacion",
    "fecha_fin_terminacion",
    "fecha_inicio_fractura",
    "fecha_fin_fractura",
    "primera_produccion",
    "primera_produccion_padron",
    "ultima_produccion",
    "meses_registrados",
    "meses_con_produccion",
    "acum_petroleo_m3",
    "acum_gas_mil_m3",
    "acum_agua_m3",
    "acum_petroleo_bbl",
    "acum_gas_mmscf",
    "acum_equivalente_m3",
    "n_registros_fractura",
    "etapas",
    "rama_m",
    "arena_tn",
    "agua_fractura_m3",
    "tipo_terminacion",
    "fuentes",
    "flags",
    "linaje",
    "fecha_descarga",
    "version_alias",
]


DATE_COLUMNS = [
    "fecha_inicio_perforacion",
    "fecha_fin_perforacion",
    "fecha_inicio_terminacion",
    "fecha_fin_terminacion",
    "fecha_inicio_fractura",
    "fecha_fin_fractura",
    "primera_produccion",
    "primera_produccion_padron",
    "ultima_produccion",
]


# --- helpers ------------------------------------------------------------------------------


def parse_point(geojson: str | None) -> tuple[float | None, float | None]:
    """``{"type":"Point","coordinates":[lon,lat]}`` -> (lon, lat); (None, None) when absent."""
    if not geojson:
        return None, None
    m = _COORD.search(str(geojson))
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def validate_coordinates(
    lon: float | None, lat: float | None, cuenca: str | None
) -> tuple[float | None, float | None, list[str]]:
    """Rule set for a published point (docs/maestro.md § coordenadas):

    1. missing or (0, 0)                      -> null, ``sin_coordenadas``
    2. lon > -50 and lat < -50 (swapped pair) -> swap, ``coordenadas_invertidas``
    3. outside Argentina's bounding box       -> keep, ``coordenadas_fuera_argentina``
    4. outside the basin's bounding box       -> keep, ``coordenadas_fuera_cuenca``
    """
    flags: list[str] = []
    if lon is None or lat is None or pd.isna(lon) or pd.isna(lat) or (lon == 0 and lat == 0):
        return None, None, ["sin_coordenadas"]
    if lon > -50 and lat < -50:
        lon, lat = lat, lon
        flags.append("coordenadas_invertidas")
    x0, x1, y0, y1 = ARGENTINA_BBOX
    if not (x0 <= lon <= x1 and y0 <= lat <= y1):
        flags.append("coordenadas_fuera_argentina")
    elif cuenca in BASIN_BBOX:
        x0, x1, y0, y1 = BASIN_BBOX[cuenca]
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            flags.append("coordenadas_fuera_cuenca")
    return lon, lat, flags


def clean_date(d, flags: list[str], flag: str = "fecha_placeholder"):
    """Dates before 1950 are placeholders in the register (ADR-013): null + flag."""
    if d is None or pd.isna(d):
        return None
    d = pd.Timestamp(d).date()
    if d < PLACEHOLDER_BEFORE:
        if flag not in flags:
            flags.append(flag)
        return None
    return d


def lateral_length(records: pd.DataFrame) -> tuple[float | None, int, list[str]]:
    """Precedence for the lateral length of a physical well (ADR-010).

    ``records`` are the well's fracture rows (all its idpozo). Returns ``(rama_m, etapas, flags)``:
    - no record                         -> (None, 0, [sin_fractura])
    - any record with length > 0        -> max of those lengths; ``rama_multiple`` when they differ
    - all lengths 0, stages >= 10       -> (None, stages, [rama_cero, rama_faltante])  # horizontal, length missing
    - all lengths 0, stages < 10        -> (None, stages, [rama_cero])                 # may be a vertical well
    Stages are the sum of ``cantidad_fracturas`` over the records (refractures included);
    ``fractura_multiples_registros`` marks wells with more than one record.
    """
    flags: list[str] = []
    if records.empty:
        return None, 0, ["sin_fractura"]
    etapas = int(records.cantidad_fracturas.fillna(0).sum())
    if len(records) > 1:
        flags.append("fractura_multiples_registros")
    pos = records.longitud_rama_horizontal_m.dropna()
    pos = pos[pos > 0]
    if pos.empty:
        flags.append("rama_cero")
        if etapas >= MIN_STAGES_HORIZONTAL:
            flags.append("rama_faltante")
        return None, etapas, flags
    if pos.nunique() > 1:
        flags.append("rama_multiple")
    return float(pos.max()), etapas, flags


def first_production(months: pd.DataFrame) -> dict:
    """From the monthly production rows of a physical well (all its idpozo):
    first and last month with oil or gas > 0, months with a record, months with production,
    cumulative volumes in published units. Never 0 for a missing date: None + flag."""
    out = {
        "primera_produccion": None,
        "ultima_produccion": None,
        "meses_registrados": 0,
        "meses_con_produccion": 0,
        "acum_petroleo_m3": None,
        "acum_gas_mil_m3": None,
        "acum_agua_m3": None,
        "flags": [],
    }
    if months.empty:
        out["flags"].append("sin_produccion")
        return out
    m = months.assign(
        mes=pd.to_datetime(
            months.anio.astype(int).astype(str) + "-" + months.mes.astype(int).astype(str) + "-01"
        )
    )
    out["meses_registrados"] = int(m.mes.nunique())
    prod = m[(m.prod_pet > 0) | (m.prod_gas > 0)]
    out["meses_con_produccion"] = int(prod.mes.nunique())
    out["acum_petroleo_m3"] = float(m.prod_pet.sum())
    out["acum_gas_mil_m3"] = float(m.prod_gas.sum())
    out["acum_agua_m3"] = float(m.prod_agua.sum())
    if prod.empty:
        out["flags"].append("nunca_produjo")
    else:
        out["primera_produccion"] = prod.mes.min().date()
        out["ultima_produccion"] = prod.mes.max().date()
    return out


# --- build ---------------------------------------------------------------------------------


def _ym(y, m):
    if y is None or m is None or pd.isna(y) or pd.isna(m):
        return None
    return date(int(y), int(m), 1)


def build_master(con: duckdb.DuckDBPyConnection, aliases: Aliases, fecha_descarga: str) -> pd.DataFrame:
    """Build the master table from DuckDB views named like the raw datasets
    (``produccion_nc``, ``fractura``, ``pozos``, ``padron_pozos``, ``listado_pozos_operadoras``).
    The last two may be absent."""
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    has_padron = "padron_pozos" in tables
    has_listado = "listado_pozos_operadoras" in tables

    # 1. universe and register ---------------------------------------------------------------
    uni = df(con, "SELECT DISTINCT idpozo FROM produccion_nc UNION SELECT DISTINCT idpozo FROM fractura")
    reg = df(
        con,
        "SELECT idpozo, sigla, area, empresa, yacimiento, formacion, cuenca, provincia, cota, profundidad, "
        "clasificacion, tipo_recurso, sub_tipo_recurso, tipopozo, tipoestado, adjiv_fecha_inicio_perf, "
        "adjiv_fecha_fin_perf, adjiv_fecha_inicio_term, adjiv_fecha_fin_term, geojson FROM pozos",
    )
    base = uni.merge(reg, on="idpozo", how="left", indicator=True)
    base["sin_padron_pozos"] = base._merge == "left_only"
    base = base.drop(columns="_merge")
    # fall back to the production / fracture spelling when the register lacks the well
    fb = df(
        con,
        "SELECT idpozo, arg_max(sigla, d) sigla, arg_max(empresa, d) empresa, arg_max(cuenca, d) cuenca, "
        "arg_max(formacion, d) formacion, arg_max(areayacimiento, d) yacimiento, arg_max(areapermisoconcesion, d) area, "
        "arg_max(provincia, d) provincia, arg_max(tipopozo, d) tipopozo, arg_max(tipoestado, d) tipoestado, "
        "arg_max(sub_tipo_recurso, d) sub_tipo_recurso, arg_max(profundidad, d) profundidad, "
        "arg_max(coordenadax, d) x, arg_max(coordenaday, d) y FROM (SELECT *, make_date(anio, mes, 1) d FROM produccion_nc) GROUP BY 1",
    )
    ff = df(
        con,
        "SELECT idpozo, min(sigla) sigla, min(cuenca) cuenca, min(formacion_productiva) formacion, "
        "min(yacimiento) yacimiento, min(areapermisoconcesion) area, min(empresa_informante) empresa, "
        "min(tipo_reservorio) tipo_recurso, min(subtipo_reservorio) sub_tipo_recurso FROM fractura GROUP BY 1",
    )
    for col in (
        "sigla",
        "empresa",
        "cuenca",
        "formacion",
        "yacimiento",
        "area",
        "provincia",
        "tipopozo",
        "tipoestado",
        "sub_tipo_recurso",
    ):
        if col in fb.columns:
            base[col] = base[col].where(
                base[col].notna() & (base[col].astype(str).str.strip() != ""),
                base.idpozo.map(fb.set_index("idpozo")[col]),
            )
        if col in ff.columns:
            base[col] = base[col].where(
                base[col].notna() & (base[col].astype(str).str.strip() != ""),
                base.idpozo.map(ff.set_index("idpozo")[col]),
            )
    base["tipo_recurso"] = base.tipo_recurso.where(
        base.tipo_recurso.notna(), base.idpozo.map(ff.set_index("idpozo").tipo_recurso)
    )
    base["sigla_norm"] = base.sigla.fillna("").map(sigla_l2)
    base.loc[base.sigla_norm == "", "sigla_norm"] = "IDPOZO-" + base.idpozo.astype(str)

    # 2. every raw spelling of every sigla -----------------------------------------------------
    parts = [
        "SELECT 'pozos' ds, idpozo, sigla FROM pozos",
        "SELECT 'produccion_nc', idpozo, sigla FROM produccion_nc",
        "SELECT 'fractura', idpozo, sigla FROM fractura",
    ]
    if has_listado:
        parts.append("SELECT 'listado_pozos_operadoras', idpozo, sigla FROM listado_pozos_operadoras")
    spell = df(con, " UNION ".join(parts)).dropna()
    spell = spell[spell.idpozo.isin(base.idpozo)]
    spell["sigla_norm"] = spell.sigla.map(sigla_l2)
    spell_by_norm = spell.groupby("sigla_norm").agg(alias=("sigla", lambda s: sorted(set(s))))
    # display spelling: the register's (trimmed, single spaces); else the most frequent one
    spell["display"] = spell.sigla.str.strip().str.replace(r"\s+", " ", regex=True)
    pref = spell[spell.ds == "pozos"].drop_duplicates("sigla_norm").set_index("sigla_norm").display
    most = spell.groupby("sigla_norm").display.agg(lambda s: s.value_counts().index[0])
    display = most.to_dict()
    display.update(pref.to_dict())
    # true variants: raw spellings that differ from the display form once trimmed
    sv = spell[spell.display != spell.sigla_norm.map(display)]
    sv = sv.groupby(["sigla", "sigla_norm"]).ds.agg(lambda s: ";".join(sorted(set(s)))).reset_index()
    sigla_variants = [(r.sigla, display[r.sigla_norm], r.ds) for r in sv.itertuples()]

    # 3. production per idpozo -------------------------------------------------------------------
    prod = df(
        con, "SELECT idpozo, anio, mes, prod_pet, prod_gas, prod_agua, empresa, tipopozo FROM produccion_nc"
    )
    prod = prod[prod.idpozo.isin(base.idpozo)]
    prod["d"] = pd.to_datetime(
        prod.anio.astype(int).astype(str) + "-" + prod.mes.astype(int).astype(str) + "-01"
    )
    oil_eq_by_id = (
        (prod.prod_pet + prod.prod_gas.map(units.gas_thousand_m3_to_m3_oil_eq)).groupby(prod.idpozo).sum()
    )

    # 4. fracture per idpozo -------------------------------------------------------------------------
    frac = df(
        con,
        "SELECT idpozo, longitud_rama_horizontal_m, cantidad_fracturas, arena_bombeada_nacional_tn, arena_bombeada_importada_tn, "
        "agua_inyectada_m3, fecha_inicio_fractura, fecha_fin_fractura, tipo_terminacion FROM fractura",
    )
    frac["fecha_inicio_fractura"] = pd.to_datetime(frac.fecha_inicio_fractura, errors="coerce")
    frac["fecha_fin_fractura"] = pd.to_datetime(frac.fecha_fin_fractura, errors="coerce")

    padron = {}
    if has_padron:
        pp = df(con, "SELECT idpozo, anio, mes FROM padron_pozos")
        padron = {int(r.idpozo): _ym(r.anio, r.mes) for r in pp.itertuples()}
    nombre_propio = {}
    if has_listado:
        lp = df(
            con,
            "SELECT idpozo, nombrepropio FROM listado_pozos_operadoras WHERE nombrepropio IS NOT NULL AND trim(nombrepropio) <> ''",
        )
        nombre_propio = dict(zip(lp.idpozo.astype(int), lp.nombrepropio.str.strip(), strict=True))

    stages_by_id = frac.groupby("idpozo").cantidad_fracturas.sum()
    fb_idx = fb.set_index("idpozo")

    def score(i: int) -> tuple:
        """Principal idpozo: most oil-equivalent production, then most stages, then lowest id."""
        return (float(oil_eq_by_id.get(i, 0.0)), float(stages_by_id.get(i, 0.0)), -i)

    today = date.today()
    rows = []
    for sigla_norm, grp in base.groupby("sigla_norm", sort=True):
        flags: list[str] = []
        lin: list[str] = []
        ids = sorted(int(i) for i in grp.idpozo)
        if len(ids) > 1:
            flags.append("multi_idpozo")
        if grp.sin_padron_pozos.any():
            flags.append("sin_padron_pozos")
        principal = max(ids, key=score)
        prow = grp[grp.idpozo == principal].iloc[0]
        lin.append(f"sigla=pozos.sigla L2 ({len(ids)} idpozo)")

        # formations
        forms = []
        for r in grp.sort_values("idpozo").itertuples():
            canon, how = aliases.formacion(r.formacion)
            if how == "missing":
                flags.append("formacion_sin_alias")
            forms.append((int(r.idpozo), canon))
        canon_set = {c for _, c in forms if c}
        if len(canon_set) > 1:
            flags.append("multi_formacion")
        form_principal = dict(forms).get(principal)
        if form_principal is None:
            flags.append("sin_formacion")
        lin.append(
            "formacion=pozos.formacion via alias/formaciones.csv; principal = idpozo con mas produccion"
        )

        # operator: latest production month over the whole well; else register; else fracture
        pm = prod[prod.idpozo.isin(ids)]
        hist: list[str] = []
        if not pm.empty:
            last = pm.sort_values("d").iloc[-1]
            op_raw, op_src = last.empresa, f"produccion_nc@{last.d:%Y-%m}"
            for e in pm.sort_values("d").empresa:
                c, _ = aliases.operadora(e)
                if c and (not hist or hist[-1] != c):
                    hist.append(c)
        else:
            op_raw, op_src = prow.empresa, "pozos.empresa"
        operadora, how = aliases.operadora(op_raw)
        if how == "missing":
            flags.append("operadora_sin_alias")
        if operadora is None:
            flags.append("sin_operadora")
        if len(hist) > 1:
            flags.append("cambio_operadora")
        reg_op, _ = aliases.operadora(prow.empresa)
        if operadora and reg_op and reg_op != operadora:
            flags.append("operadora_difiere_pozos")
        lin.append(f"operadora={op_src} via alias/operadoras.csv")

        # register attributes (principal row) + consistency inside the group
        for col, flag in (
            ("area", "area_multiple"),
            ("yacimiento", "yacimiento_multiple"),
            ("cuenca", "cuenca_multiple"),
        ):
            if grp[col].dropna().nunique() > 1:
                flags.append(flag)
        tipo_recurso = prow.tipo_recurso
        if grp.tipo_recurso.dropna().nunique() > 1:
            flags.append("tipo_recurso_mixto")
            if (grp.tipo_recurso == "NO CONVENCIONAL").any():
                tipo_recurso = "NO CONVENCIONAL"
        sub = prow.sub_tipo_recurso
        if isinstance(sub, str) and sub.strip().lower() == "no informado":
            sub = None

        # coordinates: register geojson of the principal row; production x/y as fallback
        lon, lat = parse_point(prow.geojson)
        coord_src = "pozos.geojson"
        if lon is None and principal in fb_idx.index:
            r = fb_idx.loc[principal]
            lon, lat, coord_src = r.x, r.y, "produccion_nc.coordenadax/y"
        pts = {parse_point(g) for g in grp.geojson.dropna()} - {(None, None)}
        if len(pts) > 1:
            flags.append("coordenadas_multiples")
        lon, lat, cflags = validate_coordinates(lon, lat, prow.cuenca)
        flags += cflags
        lin.append(f"coordenadas={coord_src} del idpozo principal")

        # depth: max over the group, 0 -> null
        depths = pd.to_numeric(grp.profundidad, errors="coerce").dropna()
        pos = depths[depths > 0]
        if pos.nunique() > 1:
            flags.append("profundidad_multiple")
        if pos.empty:
            prof = None
            if not depths.empty:
                flags.append("profundidad_cero")
        else:
            prof = float(pos.max())
            if prof > DEPTH_MAX_M:
                flags.append("profundidad_sospechosa")
        cota = pd.to_numeric(grp.cota, errors="coerce").dropna()
        cota_m = float(cota.iloc[0]) if not cota.empty else None
        lin.append("profundidad=pozos.profundidad max>0 del grupo")

        # drilling / completion dates from the register
        d_ini_perf = clean_date(pd.to_datetime(grp.adjiv_fecha_inicio_perf, errors="coerce").min(), flags)
        d_fin_perf = clean_date(pd.to_datetime(grp.adjiv_fecha_fin_perf, errors="coerce").max(), flags)
        d_ini_term = clean_date(pd.to_datetime(grp.adjiv_fecha_inicio_term, errors="coerce").min(), flags)
        d_fin_term = clean_date(pd.to_datetime(grp.adjiv_fecha_fin_term, errors="coerce").max(), flags)
        if d_ini_perf and d_fin_perf and d_fin_perf < d_ini_perf:
            flags.append("fechas_inconsistentes")
        if d_fin_perf and d_ini_term and d_ini_term < d_fin_perf:
            flags.append("terminacion_antes_de_perforar")
        for dd in (d_ini_perf, d_fin_perf, d_ini_term, d_fin_term):
            if dd and dd > today:
                flags.append("fecha_futura")
                break
        lin.append("fechas_perforacion=pozos.adjiv_* (min inicio, max fin; <1950 = nulo)")

        # production
        fp = first_production(pm[["anio", "mes", "prod_pet", "prod_gas", "prod_agua"]])
        flags += fp.pop("flags")
        pp_dates = [padron[i] for i in ids if i in padron]
        pp_first = min(pp_dates) if pp_dates else None
        if has_padron and not pp_dates:
            flags.append("sin_padron_primera_produccion")
        if fp["primera_produccion"] and pp_first and fp["primera_produccion"] != pp_first:
            flags.append("primera_produccion_difiere_padron")
        lin.append(
            f"produccion=produccion_nc suma de {len(ids)} idpozo; primera = primer mes con petroleo o gas > 0"
        )

        # fracture
        fr = frac[frac.idpozo.isin(ids)]
        rama, etapas, fflags = lateral_length(fr)
        flags += fflags
        if fr.empty:
            arena = agua_fr = None
            f_ini = f_fin = None
            tipo_term = None
        else:
            arena = float(
                (fr.arena_bombeada_nacional_tn.fillna(0) + fr.arena_bombeada_importada_tn.fillna(0)).sum()
            )
            agua_fr = float(fr.agua_inyectada_m3.fillna(0).sum())
            f_ini = fr.fecha_inicio_fractura.min()
            f_fin = fr.fecha_fin_fractura.max()
            f_ini = f_ini.date() if pd.notna(f_ini) else None
            f_fin = f_fin.date() if pd.notna(f_fin) else None
            if f_ini and f_ini > today:
                flags.append("fractura_fecha_futura")
            tt = fr.tipo_terminacion.dropna()
            tipo_term = tt.mode().iloc[0] if not tt.empty else None
        lin.append("rama=fractura.longitud_rama_horizontal_m max>0; etapas=suma cantidad_fracturas")

        fuentes = ["pozos"] if not grp.sin_padron_pozos.all() else []
        if not pm.empty:
            fuentes.append("produccion_nc")
        if not fr.empty:
            fuentes.append("fractura")
        if pp_dates:
            fuentes.append("padron_pozos")
        if any(i in nombre_propio for i in ids):
            fuentes.append("listado_pozos_operadoras")

        alias_list = spell_by_norm.alias.get(sigla_norm, [prow.sigla] if isinstance(prow.sigla, str) else [])
        rows.append(
            {
                "sigla": display.get(sigla_norm, sigla_norm),
                "sigla_clave": sigla_norm,
                "alias_sigla": SEP.join(alias_list),
                "idpozos": SEP.join(str(i) for i in ids),
                "n_idpozo": len(ids),
                "idpozo_principal": principal,
                "nombre_propio": nombre_propio.get(principal),
                "operadora": operadora,
                "operadoras_historicas": SEP.join(hist) if hist else None,
                "formacion_principal": form_principal,
                "formaciones": SEP.join(f"{i}:{c or ''}" for i, c in forms),
                "area": prow.area,
                "yacimiento": prow.yacimiento,
                "cuenca": prow.cuenca,
                "provincia": prow.provincia,
                "tipo_recurso": tipo_recurso,
                "sub_tipo_recurso": sub,
                "tipo_pozo": prow.tipopozo,
                "clasificacion": prow.clasificacion,
                "estado": prow.tipoestado,
                "longitud": lon,
                "latitud": lat,
                "cota_m": cota_m,
                "profundidad_m": prof,
                "fecha_inicio_perforacion": d_ini_perf,
                "fecha_fin_perforacion": d_fin_perf,
                "fecha_inicio_terminacion": d_ini_term,
                "fecha_fin_terminacion": d_fin_term,
                "fecha_inicio_fractura": f_ini,
                "fecha_fin_fractura": f_fin,
                "primera_produccion": fp["primera_produccion"],
                "primera_produccion_padron": pp_first,
                "ultima_produccion": fp["ultima_produccion"],
                "meses_registrados": fp["meses_registrados"],
                "meses_con_produccion": fp["meses_con_produccion"],
                "acum_petroleo_m3": fp["acum_petroleo_m3"],
                "acum_gas_mil_m3": fp["acum_gas_mil_m3"],
                "acum_agua_m3": fp["acum_agua_m3"],
                "acum_petroleo_bbl": units.m3_to_bbl(fp["acum_petroleo_m3"])
                if fp["acum_petroleo_m3"] is not None
                else None,
                "acum_gas_mmscf": units.thousand_m3_to_mmscf(fp["acum_gas_mil_m3"])
                if fp["acum_gas_mil_m3"] is not None
                else None,
                "acum_equivalente_m3": units.oil_eq_m3(fp["acum_petroleo_m3"], fp["acum_gas_mil_m3"])
                if fp["acum_petroleo_m3"] is not None
                else None,
                "n_registros_fractura": int(len(fr)),
                "etapas": etapas if not fr.empty else None,
                "rama_m": rama,
                "arena_tn": arena,
                "agua_fractura_m3": agua_fr,
                "tipo_terminacion": tipo_term,
                "fuentes": SEP.join(fuentes),
                "flags": SEP.join(dict.fromkeys(flags)),
                "linaje": "; ".join(lin),
                "fecha_descarga": fecha_descarga,
                "version_alias": aliases.version,
            }
        )
    out = pd.DataFrame(rows, columns=COLUMNS)
    for c in DATE_COLUMNS:
        out[c] = pd.to_datetime(out[c], errors="coerce")
    out["etapas"] = out.etapas.astype("Int64")
    out.attrs["sigla_variants"] = sigla_variants
    return out


# --- publish ---------------------------------------------------------------------------------


def publish(root: Path, master: pd.DataFrame, day: date) -> tuple[Path, Path]:
    out_dir = root / "data" / "publicado" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "pozos.csv"
    pq_path = out_dir / "pozos.parquet"
    master.to_csv(csv_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")
    con = duckdb.connect(":memory:")
    con.register("m", master)
    con.execute(f"COPY m TO '{pq_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    return csv_path, pq_path


# --- report ----------------------------------------------------------------------------------


def _count_flag(master: pd.DataFrame, flag: str) -> int:
    return int(master["flags"].fillna("").str.split(SEP).map(lambda fs: flag in fs).sum())


def make_charts(docs: Path, master: pd.DataFrame) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": SURFACE})
    out = []

    def style(ax, title, ylabel=""):
        ax.set_title(title, loc="left", fontsize=11, color="#0b0b0b", pad=10)
        ax.set_ylabel(ylabel, color=INK, fontsize=9)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color("#c3c2b7")
        ax.set_axisbelow(True)
        ax.set_facecolor(SURFACE)

    nq = master[master.cuenca == "NEUQUINA"]

    # 1. physical wells per operator (top 10), Neuquina
    fig, ax = plt.subplots(figsize=(8, 3.9))
    top = nq.operadora.value_counts().head(10).sort_values()
    ax.barh(top.index, top.values, color=BLUE, height=0.6)
    for y, v in enumerate(top.values):
        ax.text(v, y, f" {v:,}", va="center", fontsize=8, color=INK)
    style(ax, "Physical wells per operator, Neuquina basin (top 10, after alias resolution)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_xlim(0, top.max() * 1.15)
    fig.tight_layout()
    p = docs / "maestro-pozos-por-operadora.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 2. wells by year of first production, split by lateral length availability
    fig, ax = plt.subplots(figsize=(8, 3.9))
    y = nq.dropna(subset=["primera_produccion"]).copy()
    y["anio"] = pd.to_datetime(y.primera_produccion).dt.year
    y["con_rama"] = y.rama_m.notna()
    piv = (
        y.groupby(["anio", "con_rama"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=[True, False], fill_value=0)
    )
    ax.bar(piv.index, piv[True], color=BLUE, label="lateral length known")
    ax.bar(
        piv.index,
        piv[False],
        bottom=piv[True],
        color=ORANGE,
        label="no lateral length (no fracture record or length = 0)",
    )
    style(ax, "Wells by year of first production, Neuquina basin", "physical wells")
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    p = docs / "maestro-primera-produccion-por-anio.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 3. lateral length distribution, horizontal wells
    fig, ax = plt.subplots(figsize=(8, 3.6))
    r = nq.rama_m.dropna()
    r = r[r >= 500]
    ax.hist(r, bins=50, color=BLUE)
    style(ax, "Lateral length (m) of wells with a known lateral >= 500 m, Neuquina basin", "wells")
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.annotate(
        f"median {r.median():,.0f} m · n = {len(r):,}",
        xy=(0.98, 0.92),
        xycoords="axes fraction",
        fontsize=8,
        color=INK,
        ha="right",
        va="top",
    )
    fig.tight_layout()
    p = docs / "maestro-longitud-rama.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)
    return out


def build_report(
    root: Path,
    master: pd.DataFrame,
    paths: tuple[Path, Path],
    day: date,
    alias_added: int,
    manifest: dict,
    raw_day: str,
) -> Path:
    informes = root / "informes"
    informes.mkdir(exist_ok=True)
    docs = root / "docs"
    make_charts(docs, master)
    nq = master[master.cuenca == "NEUQUINA"]
    n_id = master.n_idpozo.sum()
    collapsed = n_id - len(master)
    n_alias_sigla = int((master.alias_sigla.str.count(re.escape(SEP)) > 0).sum())
    aliases = load_aliases(root / "alias")
    ops_merged = len(aliases.operadoras.rows) - len({r["canonico"] for r in aliases.operadoras.rows})
    fm_merged = len(aliases.formaciones.rows) - len({r["canonico"] for r in aliases.formaciones.rows})

    flag_counts = (
        master["flags"]
        .fillna("")
        .str.split(SEP)
        .explode()
        .replace("", pd.NA)
        .dropna()
        .value_counts()
        .rename_axis("flag")
        .reset_index(name="wells")
    )
    flag_counts["%"] = (100 * flag_counts.wells / len(master)).map(lambda v: f"{v:.1f}")

    by_op = nq.operadora.value_counts().head(10).rename_axis("operadora").reset_index(name="physical wells")
    by_op["with lateral length"] = (
        by_op.operadora.map(nq[nq.rama_m.notna()].operadora.value_counts()).fillna(0).astype(int)
    )
    by_op["producing"] = (
        by_op.operadora.map(nq[nq.primera_produccion.notna()].operadora.value_counts()).fillna(0).astype(int)
    )
    by_fm = (
        nq.formacion_principal.value_counts()
        .head(10)
        .rename_axis("formacion_principal")
        .reset_index(name="physical wells")
    )
    by_fm["median lateral (m)"] = by_fm.formacion_principal.map(
        nq.groupby("formacion_principal").rama_m.median()
    ).round(0)
    by_basin = (
        master.groupby(["cuenca", "tipo_recurso"], dropna=False)
        .size()
        .reset_index(name="physical wells")
        .sort_values("physical wells", ascending=False)
    )

    prod_vs_padron = master.dropna(subset=["primera_produccion", "primera_produccion_padron"])
    same_year = int(
        (
            pd.to_datetime(prod_vs_padron.primera_produccion).dt.year
            == pd.to_datetime(prod_vs_padron.primera_produccion_padron).dt.year
        ).sum()
    )
    padron_jan = int((pd.to_datetime(prod_vs_padron.primera_produccion_padron).dt.month == 1).sum())

    rama_known = int(nq.rama_m.notna().sum())
    rama_faltante = _count_flag(nq, "rama_faltante")
    sin_frac = _count_flag(nq, "sin_fractura")
    rama_cero = _count_flag(nq, "rama_cero")
    inv = _count_flag(master, "coordenadas_invertidas")
    fuera = _count_flag(master, "coordenadas_fuera_cuenca") + _count_flag(
        master, "coordenadas_fuera_argentina"
    )
    sin_coord = _count_flag(master, "sin_coordenadas")
    placeholder = _count_flag(master, "fecha_placeholder")
    cambio_op = _count_flag(master, "cambio_operadora")

    L: list[str] = []
    L.append(f"# Well master report — {day.isoformat()}\n")
    L.append(
        "Phase 1 of the observatory: *one row per physical well*. Built by `vma/master.py` from the raw download of "
        f"`{raw_day}` (`data/raw/{raw_day}/`), published as "
        f"`{paths[0].relative_to(root).as_posix()}` and `{paths[1].relative_to(root).as_posix()}` "
        "(not versioned; rebuild with `python pipeline.py master`). Column definitions and rules: "
        "[`docs/maestro.md`](../docs/maestro.md). Decisions: ADR-010 to ADR-014 in "
        "[`docs/decisiones.md`](../docs/decisiones.md).\n"
    )
    L.append("## 1. Identity\n")
    L.append(
        md_table(
            pd.DataFrame(
                [
                    {"measure": "idpozo in scope (production ∪ fracture)", "value": int(n_id)},
                    {"measure": "physical wells (sigla at level L2)", "value": len(master)},
                    {"measure": "idpozo collapsed into another idpozo's well", "value": int(collapsed)},
                    {"measure": "wells with more than one idpozo", "value": int((master.n_idpozo > 1).sum())},
                    {
                        "measure": "of which with more than one formation",
                        "value": _count_flag(master, "multi_formacion"),
                    },
                    {"measure": "wells whose sigla has more than one raw spelling", "value": n_alias_sigla},
                    {"measure": "sigla spellings added to alias/siglas.csv this run", "value": alias_added},
                    {
                        "measure": "operator names merged into another (alias/operadoras.csv)",
                        "value": ops_merged,
                    },
                    {
                        "measure": "formation names merged into another (alias/formaciones.csv)",
                        "value": fm_merged,
                    },
                    {
                        "measure": "wells with an operator not in the alias table",
                        "value": _count_flag(master, "operadora_sin_alias"),
                    },
                    {"measure": "wells that changed operator in the production history", "value": cambio_op},
                    {
                        "measure": "wells not in the register (pozos)",
                        "value": _count_flag(master, "sin_padron_pozos"),
                    },
                ]
            )
        )
    )
    L.append("\nPhysical wells by basin and resource type:\n")
    L.append(md_table(by_basin))
    L.append("\n## 2. Coordinates, depth, dates\n")
    L.append(
        md_table(
            pd.DataFrame(
                [
                    {"rule": "longitude/latitude swapped -> corrected", "wells": inv},
                    {"rule": "outside basin or country bounding box (kept, flagged)", "wells": fuera},
                    {"rule": "no coordinates", "wells": sin_coord},
                    {
                        "rule": "idpozo of the same well with different points",
                        "wells": _count_flag(master, "coordenadas_multiples"),
                    },
                    {"rule": "depth = 0 -> null", "wells": _count_flag(master, "profundidad_cero")},
                    {
                        "rule": f"depth > {DEPTH_MAX_M:,.0f} m (kept, flagged)",
                        "wells": _count_flag(master, "profundidad_sospechosa"),
                    },
                    {
                        "rule": "drilling/completion date before 1950 -> null (placeholder)",
                        "wells": placeholder,
                    },
                    {
                        "rule": "no drilling start date (empty or placeholder)",
                        "wells": int(master.fecha_inicio_perforacion.isna().sum()),
                    },
                    {
                        "rule": "completion starts before drilling ends",
                        "wells": _count_flag(master, "terminacion_antes_de_perforar"),
                    },
                ]
            )
        )
    )
    L.append("\n## 3. First production: computed vs. padrón\n")
    L.append(
        f"The padrón publishes a first-production month per `idpozo`; the master computes it as the first month with "
        f"oil or gas > 0 in the production file. Of {len(prod_vs_padron):,} wells with both values, "
        f"{int((prod_vs_padron.primera_produccion == prod_vs_padron.primera_produccion_padron).sum()):,} agree on the month, "
        f"{same_year:,} agree on the year, and {padron_jan:,} padrón dates fall in January: the padrón is, in practice, "
        f"a year of first production, not a month. The master keeps both columns.\n"
    )
    L.append("## 4. Fracture: lateral length and stages (Neuquina)\n")
    L.append(
        md_table(
            pd.DataFrame(
                [
                    {"measure": "physical wells, Neuquina", "value": len(nq)},
                    {"measure": "with a fracture record", "value": len(nq) - sin_frac},
                    {"measure": "without any fracture record", "value": sin_frac},
                    {"measure": "with lateral length > 0", "value": rama_known},
                    {"measure": "fracture record but all lengths = 0", "value": rama_cero},
                    {
                        "measure": f"of which with >= {MIN_STAGES_HORIZONTAL} stages (`rama_faltante`: horizontal well, length missing)",
                        "value": rama_faltante,
                    },
                    {
                        "measure": "with several records and different lengths > 0 (`rama_multiple`, max kept)",
                        "value": _count_flag(nq, "rama_multiple"),
                    },
                    {
                        "measure": "with more than one fracture record",
                        "value": _count_flag(nq, "fractura_multiples_registros"),
                    },
                    {
                        "measure": "median lateral length, wells >= 500 m (m)",
                        "value": float(nq.rama_m[nq.rama_m >= 500].median()),
                    },
                    {
                        "measure": "median stages, wells with lateral >= 500 m",
                        "value": float(nq.etapas[nq.rama_m >= 500].median()),
                    },
                ]
            )
        )
    )
    L.append("\n## 5. Distribution by operator and formation (Neuquina, top 10)\n")
    L.append(md_table(by_op))
    L.append("")
    L.append(md_table(by_fm))
    L.append("\n![wells per operator](../docs/maestro-pozos-por-operadora.png)")
    L.append("![first production per year](../docs/maestro-primera-produccion-por-anio.png)")
    L.append("![lateral length](../docs/maestro-longitud-rama.png)\n")
    L.append("## 6. Flags\n")
    L.append(
        "Every rule that fired, counted over the whole master (a well can carry several flags; definitions in `docs/maestro.md`):\n"
    )
    L.append(md_table(flag_counts))
    L.append("\n## 7. Inputs\n")
    L.append(
        md_table(
            pd.DataFrame(
                [
                    {
                        "key": m["key"],
                        "bytes": m["bytes"],
                        "sha256": m["sha256"][:12] + "…",
                        "CKAN last_modified": (m.get("ckan_last_modified") or "")[:10],
                    }
                    for m in manifest["sources"]
                ]
            )
        )
    )
    L.append(
        f"\nAlias tables version: `{master.version_alias.iloc[0] if len(master) else ''}` (max `desde` across `alias/*.csv`).\n"
    )
    path = informes / f"maestro-{day.isoformat()}.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


# --- entry point --------------------------------------------------------------------------------


def run(root: Path, today: date | None = None) -> Path:
    today = today or date.today()
    con, manifest = connect_raw(root)
    raw = latest_raw_dir(root)
    aliases = load_aliases(root / "alias")
    master = build_master(con, aliases, raw.name)
    rows, added = update_siglas(aliases.siglas, master.attrs["sigla_variants"], today)
    write_alias(root / "alias" / "siglas.csv", rows)
    if added:  # the version stamp of the table changed: rebuild so rows carry it
        aliases = load_aliases(root / "alias")
        master["version_alias"] = aliases.version
    paths = publish(root, master, today)
    report = build_report(root, master, paths, today, added, manifest, raw.name)
    print(f"{len(master):,} physical wells -> {paths[0]}  {paths[1]}\nreport: {report}")
    return report


if __name__ == "__main__":  # pragma: no cover
    run(Path(__file__).resolve().parents[1])
