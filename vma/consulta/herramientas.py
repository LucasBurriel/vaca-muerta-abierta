"""The closed set of read-only tools the agent (and the MCP server) can call (ADR-025).

Every tool is a pure function over a :class:`~vma.consulta.datos.Datos` and returns the same envelope::

    {
      "datos": ...,                                   # the answer, JSON-safe
      "cita": {"tabla", "columnas", "filtros", "regla_doc"},   # where every number comes from
      "exclusiones": [...],                           # what was left out and why (never silent)
      "notas": [...],                                 # caveats: producing days, provisional window, source limits
      "fecha_datos": "YYYY-MM-DD", "version_maestro": "YYYY-MM-DD", "fuente": "parquet" | "json"
    }

The model never writes SQL against the data: each tool builds its own parametrised query from an allowlist of
columns. ``sql_solo_lectura`` exists but is opt-in (``--sql``), SELECT-only, allowlisted and LIMITed (ADR-025).
Numbers are rounded to :data:`SIG` significant digits so the model can quote them verbatim.
"""

from __future__ import annotations

import math
import re
import threading
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from vma.consulta.datos import DOCS, NIVELES, TABLAS, Datos
from vma.normalize import formation_key, operator_key, sigla_l2, sigla_l3, sigla_l4
from vma.propios import cargar as P
from vma.propios import comparar as K
from vma.simulacion import campania as SC
from vma.simulacion import declinacion as DC
from vma.simulacion import series as SS

SIG = 4  # significant digits in every number returned (the site uses the same, vma/site.py)
MAX_FILAS = 50  # rows a tool returns at most; the tool says when it cut
N_MIN = 5  # ADR-017: nothing aggregated under 5 wells is a statistic

# Indicator columns a tool may aggregate (comparar_grupo, ranking). Units from docs/indicadores.md.
METRICAS: dict[str, str] = {
    "rama_m": "m de rama lateral",
    "etapas": "etapas de fractura",
    "etapas_por_100m": "etapas por 100 m de rama",
    "arena_tn_por_m": "t de arena por m de rama",
    "agua_fractura_m3_por_m": "m³ de agua de fractura por m de rama",
    "dias_efectivos_total": "días efectivos de producción",
    "gor6_m3_m3": "m³ gas / m³ petróleo, acumulado 6 meses",
    "gor12_m3_m3": "m³ gas / m³ petróleo, acumulado 12 meses",
    "corte_agua6": "fracción de agua en el líquido, acumulado 6 meses",
    "corte_agua12": "fracción de agua en el líquido, acumulado 12 meses",
}
for _n in (30, 90, 180):
    for _f, _u in (("petroleo", "m³/d"), ("gas", "mil m³/d"), ("equivalente", "m³ eq/d")):
        _suf = "m3_d" if _f != "gas" else "mil_m3_d"
        METRICAS[f"ip{_n}_{_f}_{_suf}"] = f"{_u} en los primeros {_n} días efectivos"
        METRICAS[f"ip{_n}_{_f}_{_suf}_por_m"] = f"{_u} por m de rama, primeros {_n} días efectivos"
for _n in (6, 12, 24):
    for _f, _u in (("petroleo", "m³"), ("gas", "mil m³"), ("agua", "m³"), ("equivalente", "m³ eq")):
        _suf = "m3" if _f != "gas" else "mil_m3"
        METRICAS[f"acum{_n}_{_f}_{_suf}"] = f"{_u} acumulados en {_n} meses calendario"
        if _f != "agua":
            METRICAS[f"acum{_n}_{_f}_{_suf}_por_m"] = f"{_u} por m de rama, acumulados en {_n} meses"

DIMENSIONES = ("operadora", "ventana", "cohorte", "area", "formacion")
FILTROS = ("formacion", "cohorte", "cohorte_desde", "cohorte_hasta", "ventana", "operadora", "area")
TASAS = (
    "petroleo_m3_d",
    "gas_mil_m3_d",
    "equivalente_m3_d",
    "petroleo_m3_d_por_m",
    "gas_mil_m3_d_por_m",
    "equivalente_m3_d_por_m",
)

NOTA_DIAS = (
    "las tasas (ip*, curvas tipo) son por día efectivo de producción (tef), no por día calendario (ADR-016); "
    "los acumulados (acum*) son por meses calendario desde el mes 0"
)

# Why an indicator is null: the flag prefixes that explain each column family (docs/indicadores.md).
_MOTIVOS = [
    (re.compile(r"^ip(30|90|180)_.*_por_m$"), ["ip{n}_dias_insuficientes", "sin_rama", "rama_corta"]),
    (re.compile(r"^ip(30|90|180)_"), ["ip{n}_dias_insuficientes", "sin_produccion", "nunca_produjo"]),
    (re.compile(r"^acum(6|12|24)_.*_por_m$"), ["acum{n}_historia_corta", "sin_rama", "rama_corta"]),
    (re.compile(r"^acum(6|12|24)_"), ["acum{n}_historia_corta", "sin_produccion", "nunca_produjo"]),
    (re.compile(r"^gor(6|12)_"), ["gor{n}_sin_petroleo", "acum{n}_historia_corta", "sin_produccion"]),
    (re.compile(r"^corte_agua(6|12)$"), ["corte_agua{n}_sin_liquido", "acum{n}_historia_corta"]),
    (re.compile(r"^(etapas_por_100m|arena_tn_por_m|agua_fractura_m3_por_m)$"), ["sin_rama", "rama_corta"]),
    (re.compile(r"^rama_m$"), ["sin_fractura", "rama_cero", "rama_faltante", "sin_rama"]),
    (re.compile(r"^etapas$"), ["sin_fractura"]),
    (re.compile(r"^outlier_"), ["outlier_no_evaluado", "fuera_alcance"]),
    (re.compile(r"^ventana"), ["gor12_sin_petroleo", "sin_produccion", "nunca_produjo"]),
    (re.compile(r"^(cohorte|primera_produccion|dias_efectivos_total)$"), ["sin_produccion", "nunca_produjo"]),
    (re.compile(r"^(longitud|latitud)$"), ["sin_coordenadas"]),
]


class ErrorHerramienta(ValueError):
    """A tool was called with something it cannot do; the message is for the model to read."""


# --- scalar helpers ---------------------------------------------------------------------------------------


def _sig(x: Any, digits: int = SIG) -> Any:
    """JSON-safe scalar rounded to ``digits`` significant digits; None for NaN/NaT; ISO for dates."""
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, (pd.Timestamp, datetime, date)):
        return None if pd.isna(x) else pd.Timestamp(x).strftime("%Y-%m-%d")
    if hasattr(x, "item"):
        x = x.item()
    if isinstance(x, str):
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
        return 0
    if f.is_integer() and abs(f) < 1e15:
        return int(f)
    return float(f"{f:.{digits}g}")


def _fila(d: dict) -> dict:
    return {k: _sig(v) for k, v in d.items()}


def _envolver(
    datos: Any,
    *,
    d: Datos,
    tabla: str,
    columnas: list[str],
    filtros: dict,
    regla_doc: str,
    exclusiones: list[str] | None = None,
    notas: list[str] | None = None,
) -> dict:
    return {
        "datos": datos,
        "cita": {
            "tabla": tabla,
            "columnas": columnas,
            "filtros": {k: v for k, v in filtros.items() if v is not None},
            "regla_doc": regla_doc,
        },
        "exclusiones": exclusiones or [],
        "notas": notas or [],
        "fecha_datos": d.fecha_descarga,
        "version_maestro": d.version_maestro,
        "fuente": d.fuente,
    }


def _nota_fuente(d: Datos, tabla: str, faltan: list[str]) -> str | None:
    if not faltan:
        return None
    return (
        f"la fuente {d.fuente} (snapshot del sitio) no trae {', '.join(faltan)} de {tabla}; "
        "con las tablas Parquet (python pipeline.py master indicadores curvas) sí"
    )


def _resolver_formacion(d: Datos, formacion: str) -> str | None:
    """The canonical spelling of a formation given a loose one (``vaca muerta`` -> ``Vaca Muerta``)."""
    if formacion is None:
        return None
    k = formation_key(formacion)
    for (f,) in d.con.execute(
        "SELECT DISTINCT formacion FROM indicadores WHERE formacion IS NOT NULL"
    ).fetchall():
        if formation_key(f) == k:
            return f
    return None


def _resolver_operadora(d: Datos, operadora: str) -> str | None:
    k = operator_key(operadora)
    cands = [
        o
        for (o,) in d.con.execute(
            "SELECT DISTINCT operadora FROM indicadores WHERE operadora IS NOT NULL"
        ).fetchall()
    ]
    for o in cands:
        if operator_key(o) == k:
            return o
    sub = [o for o in cands if k and k in operator_key(o)]
    return sub[0] if len(sub) == 1 else None


def _where_filtros(d: Datos, filtros: dict) -> tuple[list[str], list, dict, list[str]]:
    """``filtros`` (allowlisted keys) -> SQL predicates, params, the resolved filters and notes."""
    preds, params, usados, notas = ["en_alcance"], [], {}, []
    for k, v in (filtros or {}).items():
        if k not in FILTROS:
            raise ErrorHerramienta(f"filtro desconocido {k!r}; los permitidos son {', '.join(FILTROS)}")
        if v is None or v == "":
            continue
        if k == "formacion":
            f = _resolver_formacion(d, str(v))
            if f is None:
                raise ErrorHerramienta(f"formación {v!r} no existe en indicadores.formacion (en alcance)")
            preds.append("formacion = ?")
            params.append(f)
            usados[k] = f
        elif k == "operadora":
            o = _resolver_operadora(d, str(v))
            if o is None:
                raise ErrorHerramienta(
                    f"operadora {v!r} no resuelve a un nombre canónico de alias/operadoras.csv; "
                    "probá con ranking(por='operadora') para ver los nombres"
                )
            preds.append("operadora = ?")
            params.append(o)
            usados[k] = o
        elif k == "cohorte":
            preds.append("cohorte = ?")
            params.append(int(v))
            usados[k] = int(v)
        elif k == "cohorte_desde":
            preds.append("cohorte >= ?")
            params.append(int(v))
            usados[k] = int(v)
        elif k == "cohorte_hasta":
            preds.append("cohorte <= ?")
            params.append(int(v))
            usados[k] = int(v)
        elif k == "ventana":
            if v not in ("petroleo", "volatil_condensado", "gas"):
                raise ErrorHerramienta("ventana debe ser petroleo, volatil_condensado o gas (ADR-020)")
            preds.append("ventana = ?")
            params.append(v)
            usados[k] = v
        elif k == "area":
            preds.append("upper(area) = upper(?)")
            params.append(str(v))
            usados[k] = str(v)
    return preds, params, usados, notas


def _check_metrica(d: Datos, metrica: str) -> None:
    if metrica not in METRICAS:
        raise ErrorHerramienta(
            f"métrica {metrica!r} no está en la lista permitida; "
            f"las métricas son: {', '.join(sorted(METRICAS))}"
        )
    if not d.tiene("indicadores", metrica):
        raise ErrorHerramienta(
            f"la fuente {d.fuente} no trae indicadores.{metrica}; "
            "con las tablas Parquet (python pipeline.py indicadores) sí. "
            f"Columnas disponibles: {', '.join(c for c, _ in d.columnas('indicadores'))}"
        )


# --- tools ------------------------------------------------------------------------------------------------


def metadatos(d: Datos) -> dict:
    """Qué datos hay: fecha de descarga, versión del maestro, fuente (parquet o json), tablas con filas y
    columnas, y los hashes SHA-256 del manifiesto de descarga. Llamar primero si hace falta fechar una respuesta."""
    tablas = {t: {"filas": d.n_filas(t), "columnas": len(d.columnas(t)), "doc": DOCS[t]} for t in TABLAS}
    fuentes = [
        {k: s.get(k) for k in ("key", "file", "sha256", "ckan_last_modified", "license")}
        for s in d.meta.get("fuentes", [])
    ]
    datos = {
        "fecha_descarga": d.fecha_descarga,
        "version_maestro": d.version_maestro,
        "fuente": d.fuente,
        "ruta": str(d.ruta),
        "tablas": tablas,
        "manifiesto": fuentes,
        "licencia_datos": d.meta.get(
            "licencia_datos", "CC-BY 4.0, Secretaría de Energía de la Nación Argentina"
        ),
        "alcance": "cuenca NEUQUINA y tipo_recurso NO CONVENCIONAL (ADR-002); el maestro incluye todas las cuencas",
    }
    notas = [NOTA_DIAS]
    if d.fuente == "json":
        notas.append(
            "fuente json: subconjunto de columnas, 4 cifras significativas, curvas tipo hasta el mes 60 y sin media "
            "(ADR-022, ADR-023)"
        )
    return _envolver(
        datos,
        d=d,
        tabla="meta",
        columnas=["fecha_descarga", "version_maestro", "manifiesto.sha256"],
        filtros={},
        regla_doc="site/data/meta.json · data/raw/<fecha>/manifest.json (ADR-005)",
        notas=notas,
    )


def describir_tabla(d: Datos, tabla: str) -> dict:
    """Columnas y tipos de una tabla publicada (pozos, indicadores, curvas_tipo), su cantidad de filas, y
    la documentación donde está la regla de cada columna. Usar antes de pedir una métrica que no se conoce."""
    if tabla not in TABLAS:
        raise ErrorHerramienta(f"tabla {tabla!r} no existe; las tablas son {', '.join(TABLAS)}")
    cols = d.columnas(tabla)
    datos = {
        "tabla": tabla,
        "filas": d.n_filas(tabla),
        "n_columnas": len(cols),
        "columnas": [{"nombre": c, "tipo": t} for c, t in cols],
        "doc": DOCS[tabla],
    }
    if tabla == "indicadores":
        datos["metricas_agregables"] = sorted(m for m in METRICAS if d.tiene("indicadores", m))
    if tabla == "curvas_tipo":
        datos["niveles"] = list(NIVELES)
        datos["tasas"] = [t for t in TASAS if d.tiene("curvas_tipo", f"{t}_p50")]
    notas = [NOTA_DIAS]
    if d.fuente == "json":
        notas.append("fuente json: sólo las columnas que usa el sitio; la lista de arriba es la disponible")
    return _envolver(
        datos,
        d=d,
        tabla=tabla,
        columnas=[c for c, _ in cols],
        filtros={},
        regla_doc=DOCS[tabla],
        notas=notas,
    )


def buscar_pozo(d: Datos, texto: str, maximo: int = 20) -> dict:
    """Busca pozos por sigla con los niveles de normalización de vma/normalize.py: L2 (mayúsculas, espacios
    simples), L3 (sin sufijo (h)/(d)), L4 (sólo letras y dígitos), y por último como subcadena. Devuelve sigla,
    sigla_clave, operadora, formación y el nivel con que coincidió. Para identificar un pozo antes de ficha_pozo."""
    texto = (texto or "").strip()
    if len(texto) < 3:
        raise ErrorHerramienta("texto demasiado corto: al menos 3 caracteres de la sigla")
    l2, l3, l4 = sigla_l2(texto), sigla_l3(texto), sigla_l4(texto)
    maximo = max(1, min(int(maximo), MAX_FILAS))
    sql = """
        SELECT k.sigla, k.sigla_clave, i.operadora, i.formacion, i.area, i.cuenca, i.en_alcance, i.cohorte,
               CASE WHEN k.l2 = ? THEN 'L2' WHEN k.l3 = ? THEN 'L3' WHEN k.l4 = ? THEN 'L4'
                    ELSE 'subcadena' END AS nivel_coincidencia
        FROM pozos_claves k LEFT JOIN indicadores i USING (sigla_clave)
        WHERE k.l2 = ? OR k.l3 = ? OR k.l4 = ? OR k.l4 LIKE '%' || ? || '%'
        ORDER BY CASE nivel_coincidencia WHEN 'L2' THEN 0 WHEN 'L3' THEN 1 WHEN 'L4' THEN 2 ELSE 3 END, k.sigla_clave
        LIMIT ?
    """
    params = [l2, l3, l4, l2, l3, l4, l4, maximo + 1]
    filas = [_fila(r) for r in d.filas(sql, params)]
    cortado = len(filas) > maximo
    filas = filas[:maximo]
    notas = []
    if cortado:
        notas.append(f"hay más de {maximo} coincidencias; se muestran las primeras, afiná la sigla")
    if not filas:
        notas.append(
            "ningún pozo coincide en ningún nivel; la sigla puede no estar en el universo del maestro (ADR-011)"
        )
    return _envolver(
        {"n": len(filas), "pozos": filas, "niveles_buscados": {"L2": l2, "L3": l3, "L4": l4}},
        d=d,
        tabla="pozos",
        columnas=["sigla", "sigla_clave", "operadora", "formacion", "area", "cuenca"],
        filtros={"texto": texto},
        regla_doc="docs/maestro.md#identity · vma/normalize.py (niveles L0-L4)",
        notas=notas,
    )


def _motivos_sin_dato(columna: str, flags: list[str]) -> str:
    for rx, patrones in _MOTIVOS:
        m = rx.match(columna)
        if not m:
            continue
        n = m.group(1) if m.groups() else ""
        hits = []
        for p in patrones:
            p = p.replace("{n}", n)
            hits += [f for f in flags if p in f]
        if hits:
            return "flags " + ", ".join(dict.fromkeys(hits))
        return (
            f"ningún flag lo explica (docs/indicadores.md); flags de la fila: {', '.join(flags) or 'ninguno'}"
        )
    return "la fuente no lo trae"


def ficha_pozo(d: Datos, sigla_clave: str) -> dict:
    """Todo lo publicado de un pozo: identidad y atributos del maestro (pozos), indicadores (IP, acumulados,
    por metro, GOR, ventana, outlier) y, para cada indicador nulo, el motivo según los flags de la fila
    ("sin dato porque"). Requiere la sigla_clave exacta (de buscar_pozo)."""
    clave = sigla_l2(sigla_clave or "")
    maestro = d.filas("SELECT * FROM pozos WHERE sigla_clave = ?", [clave])
    if not maestro:
        raise ErrorHerramienta(f"sigla_clave {clave!r} no está en pozos; usá buscar_pozo primero")
    ind = d.filas("SELECT * FROM indicadores WHERE sigla_clave = ?", [clave])
    m = _fila(maestro[0])
    i = _fila(ind[0]) if ind else {}
    flags = sorted(set((str(m.get("flags") or "") + "|" + str(i.get("flags") or "")).split("|")) - {""})
    sin_dato = {}
    for col, val in {**{k: v for k, v in m.items() if k not in i}, **i}.items():
        if val is None and col not in ("flags", "linaje", "nombre_propio", "ventana_fuente"):
            sin_dato[col] = _motivos_sin_dato(col, flags)
    m.pop("linaje", None)
    linaje = (ind[0].get("linaje") if ind else None) or maestro[0].get("linaje")
    notas = [NOTA_DIAS]
    if i.get("ventana_fuente") in ("gor6", "gor_total"):
        notas.append(f"ventana provisoria: clasificada con {i['ventana_fuente']}, no con gor12 (ADR-020)")
    if i.get("outlier_ip90_m") is True:
        notas.append(
            "marcado outlier de IP90 por metro en su formación (ADR-018): está en la tabla, no se borró"
        )
    if not i.get("en_alcance", True):
        notas.append("fuera de alcance (ADR-002): sin evaluación de outliers ni curva tipo")
    nota_f = _nota_fuente(d, "pozos", d.faltantes("pozos", ["linaje", "alias_sigla", "idpozos"]))
    if nota_f:
        notas.append(nota_f)
    datos = {"maestro": m, "indicadores": i, "flags": flags, "sin_dato_porque": sin_dato, "linaje": linaje}
    return _envolver(
        datos,
        d=d,
        tabla="pozos + indicadores",
        columnas=sorted(set(m) | set(i)),
        filtros={"sigla_clave": clave},
        regla_doc="docs/maestro.md · docs/indicadores.md (flags)",
        notas=notas,
    )


def _agregado(d: Datos, metrica: str, por: str, preds: list[str], params: list, incluye_outliers: bool):
    """Median, quartiles and counts of ``metrica`` by ``por`` for the filtered in-scope wells."""
    if por not in DIMENSIONES:
        raise ErrorHerramienta(
            f"dimensión {por!r} no permitida; las dimensiones son {', '.join(DIMENSIONES)}"
        )
    if not d.tiene("indicadores", por):
        raise ErrorHerramienta(f"la fuente {d.fuente} no trae indicadores.{por}")
    preds = list(preds)
    exclusiones = []
    if not incluye_outliers:
        preds.append("coalesce(outlier_ip90_m, false) = false")
        exclusiones.append("outlier_ip90_m = True excluidos (ADR-018)")
    where = " AND ".join(preds)
    sql = f"""
        SELECT {por} AS grupo,
               count(*) AS n_pozos,
               count({metrica}) AS n_con_dato,
               median({metrica}) AS mediana,
               quantile_cont({metrica}, 0.25) AS p25,
               quantile_cont({metrica}, 0.75) AS p75
        FROM indicadores WHERE {where}
        GROUP BY 1
    """
    return d.filas(sql, params), exclusiones


def _conteo_motivos(d: Datos, metrica: str, preds: list[str], params: list) -> dict[str, int]:
    """How many filtered wells have ``metrica`` null, by the flag that explains it."""
    where = " AND ".join(preds)
    filas = d.filas(f"SELECT flags FROM indicadores WHERE {where} AND {metrica} IS NULL", params)
    out: dict[str, int] = {}
    for r in filas:
        fl = [f for f in str(r.get("flags") or "").split("|") if f]
        motivo = _motivos_sin_dato(metrica, fl)
        out[motivo] = out.get(motivo, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def comparar_grupo(
    d: Datos,
    formacion: str,
    cohorte: int | None = None,
    dimension: str = "operadora",
    metrica: str = "ip90_petroleo_m3_d_por_m",
    n_min: int = N_MIN,
    incluye_outliers: bool = True,
    ventana: str | None = None,
) -> dict:
    """Compara una métrica de indicadores entre grupos de una formación (y opcionalmente una cohorte y una
    ventana): mediana, P25, P75, n_pozos y n_con_dato por grupo. dimension = operadora | ventana | cohorte |
    area. Los grupos con menos de n_min pozos con dato se listan aparte, no se mezclan. Dice cuántos pozos
    quedaron sin dato y por qué flag."""
    _check_metrica(d, metrica)
    preds, params, usados, notas = _where_filtros(
        d, {"formacion": formacion, "cohorte": cohorte, "ventana": ventana}
    )
    n_min = max(1, int(n_min))
    filas, exclusiones = _agregado(d, metrica, dimension, preds, params, incluye_outliers)
    grupos, chicos = [], []
    for r in filas:
        fila = _fila(r)
        if fila["grupo"] is None:
            fila["grupo"] = "(sin dato)"
        (grupos if (r["n_con_dato"] or 0) >= n_min else chicos).append(fila)
    grupos.sort(key=lambda f: (f["mediana"] is None, -(f["mediana"] or 0)))
    chicos.sort(key=lambda f: -(f["n_pozos"] or 0))
    if chicos:
        exclusiones.append(
            f"{len(chicos)} grupo(s) con menos de {n_min} pozos con dato no entran en la comparación "
            f"(ADR-017); están en 'grupos_chicos' sólo con su n"
        )
    for c in chicos:
        for k in ("mediana", "p25", "p75"):
            c[k] = None
    motivos = _conteo_motivos(d, metrica, preds, params)
    total = sum(r["n_pozos"] for r in filas)
    con_dato = sum(r["n_con_dato"] for r in filas)
    notas.append(NOTA_DIAS)
    if metrica.endswith("_por_m"):
        notas.append("por metro sólo con rama_m conocida y >= 500 m (ADR-019): los demás cuentan en sin_dato")
    datos = {
        "metrica": metrica,
        "unidad": METRICAS[metrica],
        "dimension": dimension,
        "n_pozos_filtrados": total,
        "n_con_dato": con_dato,
        "sin_dato_porque": motivos,
        "grupos": grupos[:MAX_FILAS],
        "grupos_chicos": chicos[:MAX_FILAS],
    }
    if len(grupos) > MAX_FILAS:
        notas.append(f"más de {MAX_FILAS} grupos; se muestran los {MAX_FILAS} de mayor mediana")
    return _envolver(
        datos,
        d=d,
        tabla="indicadores",
        columnas=[metrica, dimension, "en_alcance", "flags"],
        filtros={**usados, "en_alcance": True, "incluye_outliers": incluye_outliers, "n_min": n_min},
        regla_doc=f"docs/indicadores.md ({metrica}); medianas y cuartiles por {dimension}; ADR-017, ADR-018",
        exclusiones=exclusiones,
        notas=notas,
    )


def ranking(
    d: Datos,
    metrica: str = "ip90_petroleo_m3_d_por_m",
    filtros: dict | None = None,
    n_min: int = N_MIN,
    por: str = "operadora",
    orden: str = "desc",
    top: int = 10,
    incluye_outliers: bool = True,
) -> dict:
    """Ordena grupos (por = operadora | area | formacion | cohorte | ventana) por la mediana de una métrica de
    indicadores, con n_pozos y n_con_dato. filtros admite formacion, cohorte, cohorte_desde, cohorte_hasta,
    ventana, operadora, area. Sólo entran grupos con al menos n_min pozos con dato; el resto se lista aparte.
    Sin ventana ni formación el ranking mezcla ventanas de fluido: la herramienta lo advierte."""
    _check_metrica(d, metrica)
    preds, params, usados, notas = _where_filtros(d, filtros or {})
    if orden not in ("asc", "desc"):
        raise ErrorHerramienta("orden debe ser asc o desc")
    n_min = max(1, int(n_min))
    top = max(1, min(int(top), MAX_FILAS))
    filas, exclusiones = _agregado(d, metrica, por, preds, params, incluye_outliers)
    entran = [_fila(r) for r in filas if (r["n_con_dato"] or 0) >= n_min and r["mediana"] is not None]
    fuera = [_fila(r) for r in filas if (r["n_con_dato"] or 0) < n_min or r["mediana"] is None]
    entran.sort(key=lambda f: f["mediana"], reverse=(orden == "desc"))
    for i, f in enumerate(entran, 1):
        f["puesto"] = i
    if fuera:
        exclusiones.append(
            f"{len(fuera)} grupo(s) con menos de {n_min} pozos con dato quedan fuera del ranking (ADR-017)"
        )
    if (
        "ventana" not in usados
        and por != "ventana"
        and not metrica.startswith(("rama", "etapas", "arena", "agua"))
    ):
        notas.append(
            "el ranking mezcla ventanas de fluido (petróleo, volátil/condensado, gas): la ventana pesa más que la "
            "operadora (ADR-020); filtrá por ventana para comparar pares"
        )
    if "formacion" not in usados and por != "formacion":
        notas.append("sin filtro de formación: mezcla formaciones; filtrá por formacion para comparar pares")
    notas.append(NOTA_DIAS)
    datos = {
        "metrica": metrica,
        "unidad": METRICAS[metrica],
        "por": por,
        "orden": orden,
        "n_grupos_en_ranking": len(entran),
        "ranking": entran[:top],
        "fuera_por_n_min": [{k: f[k] for k in ("grupo", "n_pozos", "n_con_dato")} for f in fuera][:MAX_FILAS],
        "sin_dato_porque": _conteo_motivos(d, metrica, preds, params),
    }
    if len(entran) > top:
        notas.append(f"se muestran los primeros {top} de {len(entran)} grupos")
    return _envolver(
        datos,
        d=d,
        tabla="indicadores",
        columnas=[metrica, por, "en_alcance", "flags"],
        filtros={**usados, "en_alcance": True, "incluye_outliers": incluye_outliers, "n_min": n_min},
        regla_doc=f"docs/indicadores.md ({metrica}); mediana por {por}; ADR-017, ADR-018, ADR-020",
        exclusiones=exclusiones,
        notas=notas,
    )


def curva_tipo(
    d: Datos,
    nivel: str,
    claves: dict,
    incluye_outliers: bool = True,
    tasa: str = "petroleo_m3_d",
    mes_max: int = 60,
) -> dict:
    """Curva tipo publicada de un grupo: P10/P50/P90 (convención petrolera: P10 es el caso alto) de una tasa
    por mes desde la primera producción, con n_pozos por mes. nivel = cohorte_formacion |
    cohorte_formacion_ventana | cohorte_formacion_operadora; claves = {cohorte, formacion[, ventana | operadora]}.
    Los meses con menos de 5 pozos vienen con estadísticos nulos y el motivo (ADR-017)."""
    if nivel not in NIVELES:
        raise ErrorHerramienta(f"nivel {nivel!r} no existe; los niveles son {', '.join(NIVELES)}")
    if tasa not in TASAS:
        raise ErrorHerramienta(f"tasa {tasa!r} no existe; las tasas son {', '.join(TASAS)}")
    if not d.tiene("curvas_tipo", f"{tasa}_p50"):
        raise ErrorHerramienta(f"la fuente {d.fuente} no trae curvas_tipo.{tasa}_p50")
    claves = dict(claves or {})
    if "cohorte" not in claves or "formacion" not in claves:
        raise ErrorHerramienta("claves necesita cohorte y formacion")
    formacion = _resolver_formacion(d, str(claves["formacion"]))
    if formacion is None:
        raise ErrorHerramienta(f"formación {claves['formacion']!r} no existe en indicadores.formacion")
    preds = ["nivel = ?", "cohorte = ?", "formacion = ?", "incluye_outliers = ?", "mes <= ?"]
    params: list = [nivel, int(claves["cohorte"]), formacion, bool(incluye_outliers), int(mes_max)]
    usados = {"nivel": nivel, "cohorte": int(claves["cohorte"]), "formacion": formacion}
    if nivel.endswith("ventana"):
        v = claves.get("ventana")
        if v not in ("petroleo", "volatil_condensado", "gas"):
            raise ErrorHerramienta("este nivel necesita claves.ventana = petroleo | volatil_condensado | gas")
        preds.append("ventana = ?")
        params.append(v)
        usados["ventana"] = v
    elif nivel.endswith("operadora"):
        o = _resolver_operadora(d, str(claves.get("operadora") or ""))
        if o is None:
            raise ErrorHerramienta(
                "este nivel necesita claves.operadora con un nombre canónico (ver ranking)"
            )
        preds.append("operadora = ?")
        params.append(o)
        usados["operadora"] = o
    estad = ["p10", "p50", "p90"] + (["media"] if d.tiene("curvas_tipo", f"{tasa}_media") else [])
    cols = ", ".join(f"{tasa}_{s} AS {s}" for s in estad)
    por_m = tasa.endswith("_por_m")
    sql = f"""
        SELECT mes, n_pozos, n_pozos_por_m, publicable, {cols}
        FROM curvas_tipo WHERE {" AND ".join(preds)} ORDER BY mes
    """
    filas = [_fila(r) for r in d.filas(sql, params)]
    exclusiones = []
    if not incluye_outliers:
        exclusiones.append("pozos con outlier_ip90_m = True excluidos (ADR-018)")
    no_pub = 0
    for f in filas:
        n_ref = f["n_pozos_por_m"] if por_m else f["n_pozos"]
        if f.get("p50") is None:
            no_pub += 1
            f["sin_dato_porque"] = (
                f"n = {n_ref} < {N_MIN} pozos ese mes (ADR-017)"
                if (n_ref or 0) < N_MIN
                else "sin dato en la fuente"
            )
    if no_pub:
        exclusiones.append(f"{no_pub} mes(es) sin estadísticos por tener menos de {N_MIN} pozos (ADR-017)")
    notas = [NOTA_DIAS, "P10 = valor que supera el 10 % de los pozos (caso alto); P90 = el 90 % (ADR-017)"]
    if not filas:
        notas.append("ningún mes para ese grupo: la cohorte/formación/clave no tiene curva publicada")
    if d.fuente == "json" and mes_max > 60:
        notas.append("fuente json: la curva llega hasta el mes 60 (ADR-023)")
    return _envolver(
        {"tasa": tasa, "n_meses": len(filas), "meses": filas[: max(mes_max + 1, 1)]},
        d=d,
        tabla="curvas_tipo",
        columnas=["mes", "n_pozos", "n_pozos_por_m", "publicable"] + [f"{tasa}_{s}" for s in estad],
        filtros={**usados, "incluye_outliers": incluye_outliers, "mes_max": mes_max},
        regla_doc="docs/indicadores.md#curvas_tipo--columns; ADR-015, ADR-016, ADR-017",
        exclusiones=exclusiones,
        notas=notas,
    )


# --- the user's own wells (F5, ADR-030) ----------------------------------------------------------------------------

NOTA_PROPIOS = (
    "mis datos viven sólo en la memoria de esta sesión: no se escriben a disco ni salen de la máquina (ADR-030); "
    "las tasas propias se computan con las mismas reglas que las publicadas (docs/mis-datos.md)"
)
DOC_PROPIOS = "docs/mis-datos.md"


def _redondear(obj: Any) -> Any:
    """``_sig`` applied through nested dicts and lists."""
    if isinstance(obj, dict):
        return {k: _redondear(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redondear(v) for v in obj]
    return _sig(obj)


def _mis(d: Datos) -> P.MisPozos:
    if d.propios is None:
        raise ErrorHerramienta(
            "no hay datos propios cargados en esta sesión: llamá cargar_mis_pozos(ruta) primero "
            "(CSV o Parquet con sigla, fecha o anio+mes, petroleo_m3, gas_mil_m3; docs/mis-datos.md)"
        )
    return d.propios


def _notas_propios(mis: P.MisPozos) -> list[str]:
    notas = [NOTA_DIAS, NOTA_PROPIOS]
    if mis.meta.get("sintetico"):
        notas.append(
            "DATOS SINTÉTICOS: pozos públicos con ruido y siglas cambiadas, no son pozos reales (meta.json)"
        )
    notas += [f"aviso de carga: {a}" for a in mis.meta.get("avisos", [])]
    return notas


def cargar_mis_pozos(d: Datos, ruta: str, mapeo: dict | None = None, ruta_pozos: str | None = None) -> dict:
    """Carga en la sesión un CSV o Parquet propio con producción mensual por pozo (sigla, fecha o anio+mes,
    petroleo_m3, gas_mil_m3; opcionales agua_m3, tef, rama_m, etapas, arena_tn, agua_fractura_m3, formacion,
    longitud, latitud, campania, ventana) y, si hace falta, un segundo archivo con los atributos por pozo.
    mapeo = {columna_canonica: columna_del_archivo} cuando los nombres no coinciden con los alias. Computa los
    indicadores con las reglas publicadas y deja las vistas mis_produccion, mis_pozos, mis_indicadores. Nada se
    escribe a disco. Devuelve el resumen de la carga, los avisos y la lista de pozos."""
    try:
        mis = P.cargar(ruta, mapeo=mapeo, ruta_pozos=ruta_pozos)
    except (FileNotFoundError, ValueError) as e:
        raise ErrorHerramienta(str(e)) from e
    P.registrar(d.con, mis)
    d.propios = mis
    ind = mis.indicadores
    por_cohorte = ind.groupby("cohorte", dropna=True).size().to_dict() if "cohorte" in ind else {}
    por_ventana = ind.groupby("ventana", dropna=True).size().to_dict() if "ventana" in ind else {}
    cols = [
        c
        for c in (
            "sigla",
            "campania",
            "formacion",
            "cohorte",
            "ventana",
            "rama_m",
            "etapas",
            "meses_con_registro",
            "ip90_petroleo_m3_d",
            "ip90_petroleo_m3_d_por_m",
            "acum12_petroleo_m3",
            "flags",
        )
        if c in ind
    ]
    datos = {
        "ruta": mis.meta.get("ruta"),
        "sintetico": mis.meta.get("sintetico", False),
        "n_pozos": mis.n_pozos,
        "filas_pozo_mes": mis.meta.get("filas"),
        "periodo": [mis.meta.get("mes_min"), mis.meta.get("mes_max")],
        "mapeo_aplicado": mis.meta.get("mapeo"),
        "formaciones": mis.meta.get("formaciones"),
        "pozos_por_cohorte": {str(int(k)): int(v) for k, v in por_cohorte.items()},
        "pozos_por_ventana": {str(k): int(v) for k, v in por_ventana.items()},
        "avisos": mis.meta.get("avisos", []),
        "pozos": [_fila(r) for r in ind[cols].head(MAX_FILAS).to_dict("records")],
    }
    notas = _notas_propios(mis)
    if mis.n_pozos > MAX_FILAS:
        notas.append(f"se listan los primeros {MAX_FILAS} de {mis.n_pozos} pozos")
    return _envolver(
        _redondear(datos),
        d=d,
        tabla="mis_produccion + mis_pozos (sesión)",
        columnas=list(mis.meta.get("mapeo", {}).keys()),
        filtros={"ruta": ruta, "ruta_pozos": ruta_pozos, "mapeo": mapeo},
        regla_doc=f"{DOC_PROPIOS}; indicadores con las reglas de docs/indicadores.md (ADR-016, ADR-019, ADR-020)",
        notas=notas,
    )


def comparar_mi_pozo(
    d: Datos,
    sigla: str,
    tasa: str = "petroleo_m3_d",
    cohorte_ref: int | None = None,
    incluye_outliers: bool = True,
    mes_max: int = 36,
) -> dict:
    """Mi pozo contra la curva tipo publicada de su grupo (cohorte × formación × ventana si está publicada, si no
    cohorte × formación): mes a mes mi tasa, P10/P50/P90 del grupo, el percentil estimado (convención petrolera:
    P10 es el caso alto) y el cociente contra P50; además mi IP90, IP90 por metro y acumulado 12 meses contra la
    mediana del grupo público con el porcentaje de pozos que supero. tasa = petroleo_m3_d | gas_mil_m3_d |
    equivalente_m3_d (o _por_m con rama >= 500 m). cohorte_ref permite comparar contra otra cohorte. Requiere
    cargar_mis_pozos antes."""
    mis = _mis(d)
    try:
        r = K.comparar_pozo(
            d,
            mis,
            sigla,
            tasa=tasa,
            cohorte_ref=cohorte_ref,
            incluye_outliers=incluye_outliers,
            mes_max=int(mes_max),
        )
    except K.ErrorComparacion as e:
        raise ErrorHerramienta(str(e)) from e
    exclusiones = []
    if not incluye_outliers:
        exclusiones.append("pozos públicos con outlier_ip90_m = True excluidos del grupo (ADR-018)")
    if r["meses_sin_curva"]:
        exclusiones.append(
            f"{r['meses_sin_curva']} mes(es) míos sin estadístico publicado (ADR-017 o fuera de la curva)"
        )
    notas = _notas_propios(mis) + [
        "percentil = posición estimada entre P90, P50 y P10 publicados (interpolación log-lineal, docs/mis-datos.md); P10 es el caso alto",
    ]
    if r["grupo"]["cohorte"] != r["grupo"]["cohorte_del_pozo"]:
        notas.append(
            f"comparado contra la cohorte {r['grupo']['cohorte']} (cohorte_ref), el pozo es de {r['grupo']['cohorte_del_pozo']}"
        )
    if r["grupo"]["nivel"] == "cohorte_formacion" and r["grupo"].get("ventana_del_pozo"):
        notas.append(
            "la curva por ventana no está publicada para ese grupo: se usa cohorte × formación (mezcla ventanas)"
        )
    if d.fuente == "json" and mes_max > 60:
        notas.append("fuente json: la curva llega hasta el mes 60 (ADR-023)")
    return _envolver(
        _redondear(r),
        d=d,
        tabla="mis_produccion + mis_indicadores (sesión) × curvas_tipo + indicadores",
        columnas=["mes", "tef_d", tasa, f"{tasa}_p10", f"{tasa}_p50", f"{tasa}_p90", "ip90_*", "acum12_*"],
        filtros={
            "sigla": sigla,
            "tasa": tasa,
            "cohorte_ref": cohorte_ref,
            "incluye_outliers": incluye_outliers,
            "mes_max": mes_max,
            **{
                f"grupo_{k}": v
                for k, v in r["grupo"].items()
                if k in ("nivel", "cohorte", "formacion", "ventana")
            },
        },
        regla_doc=f"{DOC_PROPIOS}#comparar_mi_pozo; curvas: docs/indicadores.md#curvas_tipo--columns; ADR-016, ADR-017",
        exclusiones=exclusiones,
        notas=notas,
    )


def comparar_mi_campania(
    d: Datos,
    filtros: dict | None = None,
    metrica: str = "ip90_petroleo_m3_d_por_m",
    cohorte_ref: int | None = None,
    incluye_outliers: bool = True,
) -> dict:
    """Mis pozos (filtros: campania, formacion, cohorte, ventana, siglas) contra sus grupos públicos, pozo por
    pozo: mi valor de la métrica, la mediana pública de su cohorte × formación × ventana, el cociente y el
    porcentaje de pozos públicos que supero; y el resumen de la campaña (mediana mía, mediana de medianas públicas,
    cuántos pozos superan la mediana pública, distribución de posiciones). Métricas: las de indicadores (ip*, acum*,
    gor*, corte_agua*, rama_m, etapas, *_por_m). Requiere cargar_mis_pozos antes."""
    mis = _mis(d)
    try:
        r = K.comparar_campania(
            d,
            mis,
            filtros=filtros,
            metrica=metrica,
            cohorte_ref=cohorte_ref,
            incluye_outliers=incluye_outliers,
        )
    except K.ErrorComparacion as e:
        raise ErrorHerramienta(str(e)) from e
    exclusiones = []
    if not incluye_outliers:
        exclusiones.append("pozos públicos con outlier_ip90_m = True excluidos de los grupos (ADR-018)")
    n_sd = sum(r["sin_dato_porque"].values())
    if n_sd:
        exclusiones.append(f"{n_sd} pozo(s) míos sin la métrica (ver sin_dato_porque)")
    if r["sin_grupo"]:
        exclusiones.append(f"{len(r['sin_grupo'])} pozo(s) míos sin grupo público publicado (ver sin_grupo)")
    notas = _notas_propios(mis)
    if metrica.endswith("_por_m"):
        notas.append("por metro sólo con rama_m conocida y >= 500 m (ADR-019), míos y públicos")
    if len(r["pozos"]) > MAX_FILAS:
        notas.append(f"se muestran {MAX_FILAS} de {len(r['pozos'])} pozos; filtrá por campaña o siglas")
        r["pozos"] = r["pozos"][:MAX_FILAS]
    return _envolver(
        _redondear(r),
        d=d,
        tabla="mis_indicadores (sesión) × indicadores",
        columnas=[metrica, "cohorte", "formacion", "ventana", "en_alcance", "outlier_ip90_m"],
        filtros={
            "filtros": filtros or {},
            "metrica": metrica,
            "cohorte_ref": cohorte_ref,
            "incluye_outliers": incluye_outliers,
        },
        regla_doc=f"{DOC_PROPIOS}#comparar_mi_campania; docs/indicadores.md ({metrica}); ADR-017, ADR-018",
        exclusiones=exclusiones,
        notas=notas,
    )


def brechas(
    d: Datos,
    sigla: str | None = None,
    filtros: dict | None = None,
    tasa: str = "petroleo_m3_d",
    cohorte_ref: int | None = None,
    incluye_outliers: bool = True,
    mes_max: int = 24,
) -> dict:
    """Dónde y cuánto están mis pozos por debajo del P50 de su grupo público: por mes (mi tasa, P50, brecha de
    tasa y de volumen = brecha × días efectivos, cociente) y acumulado hasta mes_max (mi acumulado, el acumulado
    que daría el P50 con mis días efectivos, la brecha en volumen y en %), con los tramos de meses por debajo (0-5,
    6-11, 12+) y el peor mes. Un pozo (sigla) o varios (filtros: campania, formacion, cohorte, ventana, siglas).
    tasa absoluta: petroleo_m3_d | gas_mil_m3_d | equivalente_m3_d. Requiere cargar_mis_pozos antes."""
    mis = _mis(d)
    try:
        r = K.brechas(
            d,
            mis,
            sigla=sigla,
            filtros=filtros,
            tasa=tasa,
            cohorte_ref=cohorte_ref,
            incluye_outliers=incluye_outliers,
            mes_max=int(mes_max),
        )
    except K.ErrorComparacion as e:
        raise ErrorHerramienta(str(e)) from e
    exclusiones = []
    if not incluye_outliers:
        exclusiones.append("pozos públicos con outlier_ip90_m = True excluidos de los grupos (ADR-018)")
    if r["sin_comparar"]:
        exclusiones.append(f"{len(r['sin_comparar'])} pozo(s) míos sin comparar (ver sin_comparar)")
    notas = _notas_propios(mis) + [
        "brecha_vol = (mi tasa - P50) × mis días efectivos del mes: es lo que hubiera producido a la tasa P50 con mi calendario, no una pérdida contable",
        "sólo meses con estadístico publicado (>= 5 pozos, ADR-017) entran en el acumulado",
    ]
    if len(r["pozos"]) > MAX_FILAS:
        notas.append(
            f"se muestran {MAX_FILAS} de {len(r['pozos'])} pozos (los de mayor brecha negativa primero)"
        )
        r["pozos"] = r["pozos"][:MAX_FILAS]
    return _envolver(
        _redondear(r),
        d=d,
        tabla="mis_produccion (sesión) × curvas_tipo",
        columnas=["mes", "tef_d", tasa, f"{tasa}_p50"],
        filtros={
            "sigla": sigla,
            "filtros": filtros or {},
            "tasa": tasa,
            "cohorte_ref": cohorte_ref,
            "incluye_outliers": incluye_outliers,
            "mes_max": mes_max,
        },
        regla_doc=f"{DOC_PROPIOS}#brechas; ADR-016, ADR-017",
        exclusiones=exclusiones,
        notas=notas,
    )


# --- simulation: decline fits and campaign Monte Carlo (F5, ADR-031) -----------------------------------------------

NOTA_SIMULACION = (
    "esto es análisis de curvas de declinación sobre datos públicos, no simulación de reservorio: no hay presiones, "
    "PVT ni geología; el EUR es el volumen que implica la curva ajustada, no una reserva (docs/simulacion.md)"
)
DOC_SIMULACION = "docs/simulacion.md"
MODELOS_TOOL = ("auto", *DC.MODELOS)


def _serie_para_ajuste(serie: pd.DataFrame, tasa: str, omitir_meses: int):
    base = tasa.removesuffix("_por_m")
    vol_col = {
        "petroleo_m3_d": "petroleo_m3",
        "gas_mil_m3_d": "gas_mil_m3",
        "equivalente_m3_d": "equivalente_m3",
    }[base]
    s = serie[serie.tef_d > 0].copy()
    s["q"] = s[vol_col] / s.tef_d
    ajuste = s[(s.mes >= int(omitir_meses)) & (s.q > 0)]
    uptime = float(serie.tef_d.sum() / serie.dias_mes.sum()) if serie.dias_mes.sum() else 1.0
    return s, ajuste, vol_col, min(max(uptime, 0.05), 1.0)


def _check_tasa_abs(tasa: str) -> None:
    if tasa not in ("petroleo_m3_d", "gas_mil_m3_d", "equivalente_m3_d"):
        raise ErrorHerramienta("tasa debe ser petroleo_m3_d, gas_mil_m3_d o equivalente_m3_d")


def pronosticar_pozo(
    d: Datos,
    sigla: str,
    mio: bool = False,
    tasa: str = "petroleo_m3_d",
    modelo: str = "auto",
    horizonte_anios: int = 20,
    omitir_meses: int = DC.OMITIR_MESES,
    n_bootstrap: int = 200,
    d_min_anual: float = DC.D_MIN_ANUAL,
    q_min: float | None = None,
    uptime: float | None = None,
) -> dict:
    """Ajusta la declinación de un pozo (público por sigla_clave, o mío con mio=true) con Arps exponencial,
    hiperbólico (con declinación terminal d_min_anual), armónico o Duong, elige por AIC si modelo=auto, y
    pronostica hasta horizonte_anios (20 o 30): EUR, EUR restante, acumulado por año, parámetros, y la banda
    P10/P50/P90 del EUR por bootstrap de residuos (n_bootstrap réplicas). Usa la tasa por día efectivo, omite los
    primeros omitir_meses meses (limpieza), integra con el uptime observado (o el dado) y corta en q_min si se
    pasa. El pozo público necesita la fuente parquet y data/raw; si no, usar pronosticar_curva_tipo. No es
    simulación de reservorio."""
    _check_tasa_abs(tasa)
    if modelo not in MODELOS_TOOL:
        raise ErrorHerramienta(f"modelo debe ser uno de {', '.join(MODELOS_TOOL)}")
    if horizonte_anios not in (10, 15, 20, 25, 30):
        raise ErrorHerramienta("horizonte_anios debe ser 10, 15, 20, 25 o 30")
    try:
        serie, meta = SS.serie_mia(d, sigla) if mio else SS.serie_publica(d, sigla)
    except SS.SinSerie as e:
        raise ErrorHerramienta(str(e)) from e
    s, aj_df, vol_col, uptime_obs = _serie_para_ajuste(serie, tasa, omitir_meses)
    up = float(uptime) if uptime is not None else uptime_obs
    try:
        if modelo == "auto":
            ajuste, tabla = DC.ajustar_auto(aj_df.mes.to_numpy() + 0.5, aj_df.q.to_numpy())
        else:
            ajuste = DC.ajustar(aj_df.mes.to_numpy() + 0.5, aj_df.q.to_numpy(), modelo)
            tabla = [{"modelo": modelo, "aic": ajuste.aic, "rmse_log": ajuste.rmse_log, "elegido": True}]
    except DC.ErrorAjuste as e:
        raise ErrorHerramienta(str(e)) from e
    H_m = int(horizonte_anios) * 12
    pr = DC.pronosticar(ajuste, s.mes.to_numpy(), s[vol_col].to_numpy(), up, H_m, q_min, d_min_anual)
    if n_bootstrap and n_bootstrap > 0:
        pr.bootstrap = DC.bootstrap_eur(
            ajuste,
            s.mes.to_numpy(),
            s[vol_col].to_numpy(),
            up,
            H_m,
            q_min,
            d_min_anual,
            n=min(int(n_bootstrap), 1000),
        )
    res = DC.resumen_pronostico(pr)
    res["comparacion_modelos"] = tabla
    res["historia"] = {
        "n_meses": int(len(serie)),
        "n_meses_ajustados": int(len(aj_df)),
        "omitidos": int(omitir_meses),
        "ultimo_mes": int(serie.mes.max()),
        "ultima_tasa": float(s.q.iloc[-1]) if len(s) else None,
        "uptime_observado": uptime_obs,
    }
    res["pozo"] = meta
    res["tasa"] = tasa
    unidad = {"petroleo_m3_d": "m³", "gas_mil_m3_d": "mil m³", "equivalente_m3_d": "m³ eq"}[tasa]
    res["unidad_volumen"] = unidad
    notas = [NOTA_DIAS, NOTA_SIMULACION]
    if meta.get("sintetico"):
        notas.append("DATOS SINTÉTICOS: el pozo mío es derivado de pozos públicos con ruido (ADR-030)")
    if mio:
        notas.append(NOTA_PROPIOS)
    if ajuste.modelo == "hiperbolico" and ajuste.parametros.get("b", 0) > 1:
        notas.append(
            f"b = {ajuste.parametros['b']:.2f} > 1: sin la declinación terminal d_min_anual el EUR divergiría; se aplica (Arps modificado)"
        )
    if len(aj_df) < 12:
        notas.append(
            f"sólo {len(aj_df)} meses ajustados: el pronóstico es débil, la banda lo refleja parcialmente"
        )
    if pr.bootstrap.get("sin_dato_porque"):
        notas.append("banda: " + pr.bootstrap["sin_dato_porque"])
    notas.append(
        "la banda bootstrap mide la incertidumbre del ajuste a esta historia, no la de un cambio de régimen (interferencia, rebaje, cierre)"
    )
    return _envolver(
        _redondear(res),
        d=d,
        tabla="mis_produccion (sesión)" if mio else "pozos + data/raw produccion_nc",
        columnas=["mes", "tef_d", vol_col],
        filtros={
            "sigla": sigla,
            "mio": mio,
            "tasa": tasa,
            "modelo": modelo,
            "horizonte_anios": horizonte_anios,
            "omitir_meses": omitir_meses,
            "n_bootstrap": n_bootstrap,
            "d_min_anual": d_min_anual,
            "q_min": q_min,
            "uptime": up,
        },
        regla_doc=f"{DOC_SIMULACION}#pronosticar_pozo; ADR-016, ADR-031",
        notas=notas,
    )


def pronosticar_curva_tipo(
    d: Datos,
    nivel: str,
    claves: dict,
    tasa: str = "petroleo_m3_d",
    modelo: str = "auto",
    horizonte_anios: int = 20,
    incluye_outliers: bool = True,
    omitir_meses: int = DC.OMITIR_MESES,
    d_min_anual: float = DC.D_MIN_ANUAL,
    uptime: float = 0.92,
    q_min: float | None = None,
) -> dict:
    """Ajusta la declinación de la curva tipo publicada de un grupo (P50, y P10 y P90 por separado) y pronostica el
    pozo tipo hasta horizonte_anios: EUR del P50 con la banda dada por los ajustes del P10 y del P90, parámetros,
    acumulado por año. Funciona con la fuente json (curvas hasta el mes 60). nivel y claves como en curva_tipo.
    uptime (días efectivos / calendario) por defecto 0.92. No es simulación de reservorio."""
    _check_tasa_abs(tasa)
    if modelo not in MODELOS_TOOL:
        raise ErrorHerramienta(f"modelo debe ser uno de {', '.join(MODELOS_TOOL)}")
    if horizonte_anios not in (10, 15, 20, 25, 30):
        raise ErrorHerramienta("horizonte_anios debe ser 10, 15, 20, 25 o 30")
    base = curva_tipo(d, nivel, claves, incluye_outliers=incluye_outliers, tasa=tasa, mes_max=600)
    meses = [m for m in base["datos"]["meses"] if m.get("p50") is not None]
    if len(meses) < DC.MIN_PUNTOS:
        raise ErrorHerramienta(f"la curva tiene {len(meses)} meses publicables; se necesitan {DC.MIN_PUNTOS}")
    t = np.array([m["mes"] for m in meses], dtype=float)
    H_m = int(horizonte_anios) * 12
    out: dict = {"tasa": tasa, "grupo": base["cita"]["filtros"], "cuantiles": {}}
    for est in ("p50", "p10", "p90"):
        q = np.array([m[est] if m.get(est) is not None else np.nan for m in meses], dtype=float)
        sel = (t >= omitir_meses) & np.isfinite(q) & (q > 0)
        if sel.sum() < max(DC.MIN_PUNTOS, 0.5 * (t >= omitir_meses).sum()):
            out["cuantiles"][est] = {
                "sin_dato_porque": (
                    f"el cuantil {est} es 0 o nulo en más de la mitad de los meses (grupo que mezcla ventanas de "
                    "fluido o con pocos pozos, ADR-020): no se ajusta"
                )
            }
            continue
        try:
            if modelo == "auto":
                aj, tabla = DC.ajustar_auto(t[sel] + 0.5, q[sel])
            else:
                aj = DC.ajustar(t[sel] + 0.5, q[sel], modelo)
                tabla = [{"modelo": modelo, "aic": aj.aic, "elegido": True}]
        except DC.ErrorAjuste as e:
            out["cuantiles"][est] = {"sin_dato_porque": str(e)}
            continue
        # the type curve has no "history volume": integrate the published months at the given uptime, then the fit
        vol_hist = q[np.isfinite(q)] * DC.DIAS_MES * uptime
        mes_hist = t[np.isfinite(q)].astype(int)
        pr = DC.pronosticar(aj, mes_hist, vol_hist, uptime, H_m, q_min, d_min_anual)
        r = DC.resumen_pronostico(pr)
        r["comparacion_modelos"] = tabla
        r.pop("banda_bootstrap", None)
        r.pop("historia_acumulada", None)
        r.pop("eur_restante", None)
        out["cuantiles"][est] = r
    if "eur" not in out["cuantiles"].get("p50", {}):
        raise ErrorHerramienta("no se pudo ajustar el P50: " + str(out["cuantiles"].get("p50")))
    out["eur_pozo_tipo"] = {
        "p50": out["cuantiles"]["p50"]["eur"],
        "p10": out["cuantiles"].get("p10", {}).get("eur"),
        "p90": out["cuantiles"].get("p90", {}).get("eur"),
        "modelo_p50": out["cuantiles"]["p50"]["modelo"],
        "meses_publicados": len(meses),
        "uptime": uptime,
    }
    unidad = {"petroleo_m3_d": "m³", "gas_mil_m3_d": "mil m³", "equivalente_m3_d": "m³ eq"}[tasa]
    out["unidad_volumen"] = unidad
    notas = [
        NOTA_DIAS,
        NOTA_SIMULACION,
        "la banda P10/P90 es el ajuste de las curvas P10 y P90 publicadas, no un intervalo del P50",
    ]
    if d.fuente == "json":
        notas.append(
            "fuente json: la curva llega hasta el mes 60 (ADR-023); el ajuste se extrapola desde ahí"
        )
    return _envolver(
        _redondear(out),
        d=d,
        tabla="curvas_tipo",
        columnas=["mes", f"{tasa}_p10", f"{tasa}_p50", f"{tasa}_p90"],
        filtros={
            **base["cita"]["filtros"],
            "tasa": tasa,
            "modelo": modelo,
            "horizonte_anios": horizonte_anios,
            "omitir_meses": omitir_meses,
            "d_min_anual": d_min_anual,
            "uptime": uptime,
            "q_min": q_min,
        },
        regla_doc=f"{DOC_SIMULACION}#pronosticar_curva_tipo; ADR-017, ADR-031",
        exclusiones=base["exclusiones"],
        notas=notas,
    )


def simular_campania(
    d: Datos,
    formacion: str,
    n_pozos: int,
    meses: int = 120,
    ventana: str | None = None,
    cohorte_ref: int | None = None,
    rama_m: float | None = None,
    ritmo_pozos_por_mes: int | None = None,
    tasa: str = "petroleo_m3_d",
    n_sim: int = 500,
    semilla: int = 0,
    uptime: float = 0.92,
    incluye_outliers: bool = True,
) -> dict:
    """Monte Carlo de una campaña de n_pozos pozos nuevos muestreados de la curva tipo publicada de formacion ×
    cohorte_ref (× ventana si se da): cada pozo simulado toma una posición en el grupo y su tasa mes a mes sale de
    los P10/P50/P90 publicados; si se pasa rama_m y el grupo tiene curva por metro, escala por la rama. Los pozos
    entran a ritmo_pozos_por_mes (por defecto todos en el mes 0). Devuelve por mes P10/P50/P90 y media de la tasa
    agregada y del acumulado, pozos en línea, y el acumulado final con banda. La banda es la dispersión publicada
    entre pozos, nada más: sin interferencia, sin instalaciones, sin precio. No es simulación de reservorio."""
    _check_tasa_abs(tasa)
    f = _resolver_formacion(d, formacion)
    if f is None:
        raise ErrorHerramienta(f"formación {formacion!r} no existe en indicadores.formacion")
    if cohorte_ref is None:
        (cohorte_ref,) = d.con.execute(
            "SELECT max(cohorte) FROM curvas_tipo WHERE formacion = ? AND nivel = 'cohorte_formacion' AND publicable AND mes >= 12",
            [f],
        ).fetchone()
        if cohorte_ref is None:
            raise ErrorHerramienta(f"ninguna cohorte de {f} tiene 12 meses publicables; pasá cohorte_ref")
    if ventana is not None and ventana not in ("petroleo", "volatil_condensado", "gas"):
        raise ErrorHerramienta("ventana debe ser petroleo, volatil_condensado o gas")
    nivel = "cohorte_formacion_ventana" if ventana else "cohorte_formacion"
    preds = ["nivel = ?", "cohorte = ?", "formacion = ?", "incluye_outliers = ?"]
    params: list = [nivel, int(cohorte_ref), f, bool(incluye_outliers)]
    if ventana:
        preds.append("ventana = ?")
        params.append(ventana)
    por_metro = bool(rama_m) and d.tiene("curvas_tipo", f"{tasa}_por_m_p50")
    col = f"{tasa}_por_m" if por_metro else tasa
    curva = d.df(
        f"SELECT mes, {col}_p10 AS p10, {col}_p50 AS p50, {col}_p90 AS p90 FROM curvas_tipo WHERE {' AND '.join(preds)} ORDER BY mes",
        params,
    )
    if por_metro and curva.p50.notna().sum() < DC.MIN_PUNTOS:
        por_metro = False
        col = tasa
        curva = d.df(
            f"SELECT mes, {col}_p10 AS p10, {col}_p50 AS p50, {col}_p90 AS p90 FROM curvas_tipo WHERE {' AND '.join(preds)} ORDER BY mes",
            params,
        )
    if curva.p50.notna().sum() < DC.MIN_PUNTOS:
        raise ErrorHerramienta(
            f"la curva {nivel} de {f} cohorte {cohorte_ref}"
            + (f" ventana {ventana}" if ventana else "")
            + f" tiene menos de {DC.MIN_PUNTOS} meses publicables (ADR-017); probá otra cohorte_ref o sin ventana"
        )
    try:
        r = SC.simular(
            curva,
            n_pozos=n_pozos,
            meses=meses,
            rama_m=rama_m,
            por_metro=por_metro,
            ritmo=ritmo_pozos_por_mes,
            n_sim=n_sim,
            semilla=semilla,
            uptime=uptime,
        )
    except SC.ErrorSimulacion as e:
        raise ErrorHerramienta(str(e)) from e
    r["grupo"] = {
        "nivel": nivel,
        "cohorte_ref": int(cohorte_ref),
        "formacion": f,
        "ventana": ventana,
        "incluye_outliers": incluye_outliers,
        "curva": col,
    }
    r["tasa"] = tasa
    r["unidad_volumen"] = {"petroleo_m3_d": "m³", "gas_mil_m3_d": "mil m³", "equivalente_m3_d": "m³ eq"}[tasa]
    notas = [
        NOTA_DIAS,
        NOTA_SIMULACION,
        "la banda es la dispersión entre pozos de la curva publicada (posición sorteada por pozo, con ruido mensual); sin interferencia padre-hijo, sin restricción de instalaciones, sin precio",
    ]
    if rama_m and not por_metro:
        notas.append(
            "rama_m ignorada: el grupo no tiene curva por metro publicable; se usó la curva absoluta"
        )
    if r["meses_extrapolados"]:
        notas.append(
            f"{r['meses_extrapolados']} meses más allá de la curva publicada: extrapolados con un ajuste hiperbólico de cada cuantil (d_min {DC.D_MIN_ANUAL:.0%} anual)"
        )
    if not ventana:
        notas.append(
            "sin ventana: la curva mezcla ventanas de fluido (ADR-020); pasá ventana para una campaña homogénea"
        )
    exclusiones = (
        [] if incluye_outliers else ["pozos con outlier_ip90_m = True excluidos de la curva (ADR-018)"]
    )
    # keep the envelope small: monthly bands at 3 significant digits already via _redondear; drop the mean series if long
    return _envolver(
        _redondear(r),
        d=d,
        tabla="curvas_tipo",
        columnas=["mes", f"{col}_p10", f"{col}_p50", f"{col}_p90"],
        filtros={
            "formacion": f,
            "cohorte_ref": int(cohorte_ref),
            "ventana": ventana,
            "n_pozos": n_pozos,
            "meses": meses,
            "rama_m": rama_m,
            "ritmo_pozos_por_mes": ritmo_pozos_por_mes,
            "tasa": tasa,
            "n_sim": n_sim,
            "semilla": semilla,
            "uptime": uptime,
            "incluye_outliers": incluye_outliers,
        },
        regla_doc=f"{DOC_SIMULACION}#simular_campania; ADR-017, ADR-031",
        exclusiones=exclusiones,
        notas=notas,
    )


# --- opt-in: read-only SQL ------------------------------------------------------------------------------------

_SQL_PROHIBIDO = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|copy|export|import|install|load|pragma|set|call|"
    r"vacuum|checkpoint|read_csv|read_parquet|read_json|glob|getenv|from_json)\b|;",
    re.IGNORECASE,
)
_TABLA_REF = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
SQL_LIMIT = 200
SQL_TIMEOUT_S = 10


def sql_solo_lectura(d: Datos, sql: str, limite: int = SQL_LIMIT) -> dict:
    """SELECT libre sobre pozos, indicadores y curvas_tipo. Opt-in (--sql): sólo SELECT, sólo esas tablas,
    sin funciones de archivo ni sentencias múltiples, LIMIT forzado y timeout. La respuesta cita la consulta
    literal como regla. Riesgo documentado en ADR-025: el modelo puede escribir una consulta sutilmente mal."""
    s = (sql or "").strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", s, re.IGNORECASE):
        raise ErrorHerramienta("sólo SELECT (o WITH ... SELECT)")
    if _SQL_PROHIBIDO.search(s):
        raise ErrorHerramienta("la consulta usa una palabra o símbolo fuera de la allowlist de sólo lectura")
    refs = {t.lower() for t in _TABLA_REF.findall(s)}
    ctes = {m.lower() for m in re.findall(r"\b(\w+)\s+as\s*\(", s, re.IGNORECASE)}
    fuera = refs - set(TABLAS) - ctes
    if fuera:
        raise ErrorHerramienta(
            f"tablas fuera de la allowlist: {', '.join(sorted(fuera))}; permitidas: {', '.join(TABLAS)}"
        )
    limite = max(1, min(int(limite), SQL_LIMIT))
    envuelto = f"SELECT * FROM ({s}) AS _q LIMIT {limite + 1}"
    con = d.con.cursor()
    resultado: dict = {}

    def correr():
        try:
            cur = con.execute(envuelto)
            resultado["cols"] = [c[0] for c in cur.description]
            resultado["rows"] = cur.fetchall()
        except Exception as e:  # noqa: BLE001 - the model needs the DuckDB message, whatever its class
            resultado["error"] = e

    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()
    hilo.join(SQL_TIMEOUT_S)
    if hilo.is_alive():
        con.interrupt()
        hilo.join(2)
        raise ErrorHerramienta(f"la consulta superó los {SQL_TIMEOUT_S} s y fue interrumpida (ADR-025)")
    con.close()
    if "error" in resultado:
        raise ErrorHerramienta(f"DuckDB: {resultado['error']}") from resultado["error"]
    cols, rows = resultado["cols"], resultado["rows"]
    filas = [_fila(dict(zip(cols, r, strict=True))) for r in rows[:limite]]
    notas = [NOTA_DIAS]
    if len(rows) > limite:
        notas.append(f"más de {limite} filas; LIMIT forzado (ADR-025)")
    return _envolver(
        {"n": len(filas), "filas": filas},
        d=d,
        tabla=", ".join(sorted(refs)) or "?",
        columnas=cols,
        filtros={"sql": s},
        regla_doc="consulta literal (sql_solo_lectura, ADR-025); verificar contra docs/indicadores.md",
        notas=notas,
    )


# --- registry (shared by the agent and the MCP server) --------------------------------------------------------

_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_FILTROS_SCHEMA = {
    "type": "object",
    "description": "filtros sobre indicadores (todos opcionales)",
    "properties": {
        "formacion": _STR,
        "cohorte": _INT,
        "cohorte_desde": _INT,
        "cohorte_hasta": _INT,
        "ventana": {"type": "string", "enum": ["petroleo", "volatil_condensado", "gas"]},
        "operadora": _STR,
        "area": _STR,
    },
    "additionalProperties": False,
}


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


HERRAMIENTAS: dict[str, dict] = {
    "metadatos": {"fn": metadatos, "schema": _schema({}, [])},
    "describir_tabla": {
        "fn": describir_tabla,
        "schema": _schema({"tabla": {"type": "string", "enum": list(TABLAS)}}, ["tabla"]),
    },
    "buscar_pozo": {
        "fn": buscar_pozo,
        "schema": _schema({"texto": _STR, "maximo": _INT}, ["texto"]),
    },
    "ficha_pozo": {"fn": ficha_pozo, "schema": _schema({"sigla_clave": _STR}, ["sigla_clave"])},
    "comparar_grupo": {
        "fn": comparar_grupo,
        "schema": _schema(
            {
                "formacion": _STR,
                "cohorte": _INT,
                "dimension": {"type": "string", "enum": list(DIMENSIONES)},
                "metrica": {"type": "string", "enum": sorted(METRICAS)},
                "n_min": _INT,
                "incluye_outliers": _BOOL,
                "ventana": {"type": "string", "enum": ["petroleo", "volatil_condensado", "gas"]},
            },
            ["formacion"],
        ),
    },
    "ranking": {
        "fn": ranking,
        "schema": _schema(
            {
                "metrica": {"type": "string", "enum": sorted(METRICAS)},
                "filtros": _FILTROS_SCHEMA,
                "n_min": _INT,
                "por": {"type": "string", "enum": list(DIMENSIONES)},
                "orden": {"type": "string", "enum": ["asc", "desc"]},
                "top": _INT,
                "incluye_outliers": _BOOL,
            },
            [],
        ),
    },
    "curva_tipo": {
        "fn": curva_tipo,
        "schema": _schema(
            {
                "nivel": {"type": "string", "enum": list(NIVELES)},
                "claves": {
                    "type": "object",
                    "properties": {"cohorte": _INT, "formacion": _STR, "ventana": _STR, "operadora": _STR},
                    "required": ["cohorte", "formacion"],
                    "additionalProperties": False,
                },
                "incluye_outliers": _BOOL,
                "tasa": {"type": "string", "enum": list(TASAS)},
                "mes_max": _INT,
            },
            ["nivel", "claves"],
        ),
    },
}
_FILTROS_MIOS_SCHEMA = {
    "type": "object",
    "description": "filtros sobre mis pozos (todos opcionales)",
    "properties": {
        "campania": _STR,
        "formacion": _STR,
        "cohorte": _INT,
        "ventana": {"type": "string", "enum": ["petroleo", "volatil_condensado", "gas"]},
        "siglas": {"type": "array", "items": _STR},
    },
    "additionalProperties": False,
}
_TASAS_MIAS = [t for t in TASAS]
HERRAMIENTAS.update(
    {
        "cargar_mis_pozos": {
            "fn": cargar_mis_pozos,
            "schema": _schema(
                {
                    "ruta": _STR,
                    "mapeo": {
                        "type": "object",
                        "additionalProperties": _STR,
                        "description": "{columna_canonica: columna_del_archivo}",
                    },
                    "ruta_pozos": _STR,
                },
                ["ruta"],
            ),
        },
        "comparar_mi_pozo": {
            "fn": comparar_mi_pozo,
            "schema": _schema(
                {
                    "sigla": _STR,
                    "tasa": {"type": "string", "enum": _TASAS_MIAS},
                    "cohorte_ref": _INT,
                    "incluye_outliers": _BOOL,
                    "mes_max": _INT,
                },
                ["sigla"],
            ),
        },
        "comparar_mi_campania": {
            "fn": comparar_mi_campania,
            "schema": _schema(
                {
                    "filtros": _FILTROS_MIOS_SCHEMA,
                    "metrica": {"type": "string", "enum": sorted(METRICAS)},
                    "cohorte_ref": _INT,
                    "incluye_outliers": _BOOL,
                },
                [],
            ),
        },
        "brechas": {
            "fn": brechas,
            "schema": _schema(
                {
                    "sigla": _STR,
                    "filtros": _FILTROS_MIOS_SCHEMA,
                    "tasa": {"type": "string", "enum": ["petroleo_m3_d", "gas_mil_m3_d", "equivalente_m3_d"]},
                    "cohorte_ref": _INT,
                    "incluye_outliers": _BOOL,
                    "mes_max": _INT,
                },
                [],
            ),
        },
    }
)
_NUM = {"type": "number"}
_TASA_ABS = {"type": "string", "enum": ["petroleo_m3_d", "gas_mil_m3_d", "equivalente_m3_d"]}
HERRAMIENTAS.update(
    {
        "pronosticar_pozo": {
            "fn": pronosticar_pozo,
            "schema": _schema(
                {
                    "sigla": _STR,
                    "mio": _BOOL,
                    "tasa": _TASA_ABS,
                    "modelo": {"type": "string", "enum": list(MODELOS_TOOL)},
                    "horizonte_anios": {"type": "integer", "enum": [10, 15, 20, 25, 30]},
                    "omitir_meses": _INT,
                    "n_bootstrap": _INT,
                    "d_min_anual": _NUM,
                    "q_min": _NUM,
                    "uptime": _NUM,
                },
                ["sigla"],
            ),
        },
        "pronosticar_curva_tipo": {
            "fn": pronosticar_curva_tipo,
            "schema": _schema(
                {
                    "nivel": {"type": "string", "enum": list(NIVELES)},
                    "claves": {
                        "type": "object",
                        "properties": {
                            "cohorte": _INT,
                            "formacion": _STR,
                            "ventana": _STR,
                            "operadora": _STR,
                        },
                        "required": ["cohorte", "formacion"],
                        "additionalProperties": False,
                    },
                    "tasa": _TASA_ABS,
                    "modelo": {"type": "string", "enum": list(MODELOS_TOOL)},
                    "horizonte_anios": {"type": "integer", "enum": [10, 15, 20, 25, 30]},
                    "incluye_outliers": _BOOL,
                    "omitir_meses": _INT,
                    "d_min_anual": _NUM,
                    "uptime": _NUM,
                    "q_min": _NUM,
                },
                ["nivel", "claves"],
            ),
        },
        "simular_campania": {
            "fn": simular_campania,
            "schema": _schema(
                {
                    "formacion": _STR,
                    "n_pozos": _INT,
                    "meses": _INT,
                    "ventana": {"type": "string", "enum": ["petroleo", "volatil_condensado", "gas"]},
                    "cohorte_ref": _INT,
                    "rama_m": _NUM,
                    "ritmo_pozos_por_mes": _INT,
                    "tasa": _TASA_ABS,
                    "n_sim": _INT,
                    "semilla": _INT,
                    "uptime": _NUM,
                    "incluye_outliers": _BOOL,
                },
                ["formacion", "n_pozos"],
            ),
        },
    }
)
HERRAMIENTAS_OPT_IN: dict[str, dict] = {
    "sql_solo_lectura": {"fn": sql_solo_lectura, "schema": _schema({"sql": _STR, "limite": _INT}, ["sql"])},
}


def descripcion(nombre: str) -> str:
    """The tool's description for the model: its docstring, whitespace collapsed."""
    fn = {**HERRAMIENTAS, **HERRAMIENTAS_OPT_IN}[nombre]["fn"]
    return " ".join((fn.__doc__ or "").split())


def definiciones(con_sql: bool = False) -> list[dict]:
    """Tool definitions in the Claude API shape (name, description, input_schema)."""
    regs = dict(HERRAMIENTAS)
    if con_sql:
        regs.update(HERRAMIENTAS_OPT_IN)
    return [
        {"name": n, "description": descripcion(n), "input_schema": r["schema"], "strict": True}
        for n, r in regs.items()
    ]


def ejecutar(d: Datos, nombre: str, entrada: dict | None, con_sql: bool = False) -> dict:
    """Run one tool by name with a dict of arguments. Unknown tool or bad arguments raise ErrorHerramienta."""
    regs = dict(HERRAMIENTAS)
    if con_sql:
        regs.update(HERRAMIENTAS_OPT_IN)
    if nombre not in regs:
        raise ErrorHerramienta(f"herramienta {nombre!r} no existe; las herramientas son {', '.join(regs)}")
    entrada = dict(entrada or {})
    permitidas = set(regs[nombre]["schema"]["properties"])
    extra = set(entrada) - permitidas
    if extra:
        raise ErrorHerramienta(f"argumentos desconocidos para {nombre}: {', '.join(sorted(extra))}")
    try:
        return regs[nombre]["fn"](d, **entrada)
    except TypeError as e:
        raise ErrorHerramienta(f"argumentos inválidos para {nombre}: {e}") from e
