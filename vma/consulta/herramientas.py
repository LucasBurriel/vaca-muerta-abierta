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

from vma.consulta.datos import DOCS, NIVELES, TODAS, Datos
from vma.normalize import formation_key, operator_key, sigla_l2, sigla_l3, sigla_l4
from vma.precios import (
    CONTRATO_GAS_DEFAULT,
    CONTRATOS_GAS,
    REGION_GAS_DEFAULT,
    REGION_PETROLEO_DEFAULT,
    SEGMENTO_GAS_DEFAULT,
    SEGMENTO_PETROLEO,
    SEGMENTOS_GAS,
    cuenca_gas_canonica,
    provincia_canonica,
)
from vma.precios import valorizar as VZ
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
    tablas = {t: {"filas": d.n_filas(t), "columnas": len(d.columnas(t)), "doc": DOCS[t]} for t in TODAS}
    if not d.tiene_precios():
        tablas["precios"]["sin_dato_porque"] = (
            "tabla precios vacía en esta fuente: corré `python pipeline.py download regalias_crudo precios_gas` y "
            "`python pipeline.py precios` (docs/precios.md)"
        )
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
    """Columnas y tipos de una tabla publicada (pozos, indicadores, curvas_tipo, precios), su cantidad de filas, y
    la documentación donde está la regla de cada columna. Usar antes de pedir una métrica que no se conoce."""
    if tabla not in TODAS:
        raise ErrorHerramienta(f"tabla {tabla!r} no existe; las tablas son {', '.join(TODAS)}")
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
    if tabla == "precios":
        datos["productos"] = {
            "petroleo": {"segmentos": [SEGMENTO_PETROLEO], "unidad_dataset": "USD/m³", "region": "provincia"},
            "gas": {
                "segmentos": list(SEGMENTOS_GAS),
                "contratos": list(CONTRATOS_GAS),
                "unidad_dataset": "USD/MMBTU",
                "region": "cuenca",
            },
        }
        datos["regiones"] = {
            p: [
                r
                for (r,) in d.con.execute(
                    "SELECT DISTINCT region FROM precios WHERE producto = ? ORDER BY 1", [p]
                ).fetchall()
            ]
            for p in ("petroleo", "gas")
        }
        if not d.tiene_precios():
            datos["sin_dato_porque"] = (
                "tabla vacía en esta fuente: python pipeline.py download regalias_crudo precios_gas && python pipeline.py precios"
            )
    notas = [NOTA_DIAS]
    if tabla == "precios" and d.fuente == "json":
        notas.append("fuente json: petróleo desde 2006 y gas sólo contrato total (ADR-034)")
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
    valorizar: dict | None = None,
) -> dict:
    """Curva tipo publicada de un grupo: P10/P50/P90 (convención petrolera: P10 es el caso alto) de una tasa
    por mes desde la primera producción, con n_pozos por mes. nivel = cohorte_formacion |
    cohorte_formacion_ventana | cohorte_formacion_operadora; claves = {cohorte, formacion[, ventana | operadora]}.
    Los meses con menos de 5 pozos vienen con estadísticos nulos y el motivo (ADR-017). Con valorizar =
    {modo: historico | flat | ultimo, precio_flat?, tasa_anual? (0.10), regalia? (0 u 0.12), mes0?, region_petroleo?,
    region_gas?, uptime? (0.92)} agrega el bloque usd: ingreso bruto en USD por mes, acumulado y VAN de las curvas
    P10/P50/P90 de petróleo y gas del grupo a precios públicos (tabla precios, docs/precios.md)."""
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
    datos = {"tasa": tasa, "n_meses": len(filas), "meses": filas[: max(mes_max + 1, 1)]}
    if valorizar is not None:
        # the absolute oil and gas curves of the same group, whatever `tasa` was asked for
        vcols = ", ".join(
            f"{c}_{s}" for c in ("petroleo_m3_d", "gas_mil_m3_d") for s in ("p10", "p50", "p90")
        )
        vfilas = [
            _fila(r)
            for r in d.filas(
                f"SELECT mes, {vcols} FROM curvas_tipo WHERE {' AND '.join(preds)} ORDER BY mes", params
            )
        ]
        uptime = float((valorizar or {}).get("uptime", 0.92))
        series = {
            est: _volumenes_curva(vfilas, uptime, ("petroleo_m3_d", "gas_mil_m3_d"), est)
            for est in ("p10", "p50", "p90")
        }
        usd = _valorizacion(
            d,
            valorizar,
            series=series,
            mes0=f"{int(claves['cohorte']):04d}-01",
            modo_default="ultimo",
            notas_extra=[
                f"volumen mensual = tasa por día efectivo × {VZ.DIAS_MES:.2f} d × uptime {uptime:g}",
                "mes0 por defecto = enero de la cohorte (modo historico); los P10 de petróleo y de gas no son los mismos pozos: la banda USD es una envolvente",
            ],
        )
        datos["usd"] = usd
        if usd and "sin_dato_porque" in usd:
            notas.append("usd: " + usd["sin_dato_porque"])
        elif usd:
            notas.append("usd: " + VZ.NOTA_BRUTO)
    return _envolver(
        datos,
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
    """Carga en la sesión un CSV o Parquet propio con producción mensual por pozo. ruta = archivo, carpeta (toma
    el *produccion* y el *atributos* que haya adentro) o el alias "sintetico" (dataset de demo de 30 pozos).
    Columnas (sigla, fecha o anio+mes,
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
    valorizar: dict | None = None,
) -> dict:
    """Mi pozo contra la curva tipo publicada de su grupo (cohorte × formación × ventana si está publicada, si no
    cohorte × formación): mes a mes mi tasa, P10/P50/P90 del grupo, el percentil estimado (convención petrolera:
    P10 es el caso alto) y el cociente contra P50; además mi IP90, IP90 por metro y acumulado 12 meses contra la
    mediana del grupo público con el porcentaje de pozos que supero. tasa = petroleo_m3_d | gas_mil_m3_d |
    equivalente_m3_d (o _por_m con rama >= 500 m). cohorte_ref permite comparar contra otra cohorte. Requiere
    cargar_mis_pozos antes. Con valorizar = {modo: historico (por defecto, precio del mes calendario) | flat |
    ultimo, precio_flat?, tasa_anual?, regalia?, region_petroleo?, region_gas?, uptime?} agrega el bloque usd:
    mi ingreso bruto (petróleo + gas) por mes, acumulado y VAN, y el del pozo tipo P10/P50/P90 del grupo."""
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
    r = _redondear(r)
    if valorizar is not None:
        r["usd"] = _usd_mi_pozo(d, mis, r, valorizar, int(mes_max))
        if r["usd"] and "sin_dato_porque" in r["usd"]:
            notas.append("usd: " + r["usd"]["sin_dato_porque"])
        elif r["usd"]:
            notas.append("usd: " + VZ.NOTA_BRUTO)
    return _envolver(
        r,
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


def _mi_serie_volumenes(mis: P.MisPozos, sigla: str, mes_max: int) -> tuple[list, list, str | None, float]:
    """(oil m³, gas mil m³ per month 0..mes_max, calendar month of month 0, observed uptime) of one of my wells."""
    g = mis.produccion[(mis.produccion.sigla == sigla) & mis.produccion.k.notna() & (mis.produccion.k >= 0)]
    g = g[g.k <= mes_max].sort_values("k")
    if g.empty:
        return [], [], None, 0.92
    n = int(g.k.max()) + 1
    petro: list = [None] * n
    gas: list = [None] * n
    for row in g.itertuples(index=False):
        petro[int(row.k)] = float(row.petroleo_m3) if pd.notna(row.petroleo_m3) else None
        gas[int(row.k)] = float(row.gas_mil_m3) if pd.notna(row.gas_mil_m3) else None
    uptime = float(g.tef_d.sum() / g.dias_mes.sum()) if g.dias_mes.sum() else 0.92
    return petro, gas, _mes_str(g.mes_fecha.iloc[0]), min(max(uptime, 0.05), 1.0)


def _usd_mi_pozo(d: Datos, mis: P.MisPozos, r: dict, valorizar: dict, mes_max: int) -> dict | None:
    """The ``usd`` block of comparar_mi_pozo: my actual volumes and the group's P10/P50/P90 type well."""
    petro, gas, mes0, uptime_obs = _mi_serie_volumenes(mis, r["pozo"]["sigla"], mes_max)
    if not petro and not gas:
        return {"sin_dato_porque": "mi pozo no tiene meses con producción desde el mes 0"}
    g = r["grupo"]
    preds = ["nivel = ?", "cohorte = ?", "formacion = ?", "incluye_outliers = ?", "mes <= ?"]
    params: list = [g["nivel"], int(g["cohorte"]), g["formacion"], bool(g["incluye_outliers"]), mes_max]
    if g.get("ventana"):
        preds.append("ventana = ?")
        params.append(g["ventana"])
    vcols = ", ".join(f"{c}_{s}" for c in ("petroleo_m3_d", "gas_mil_m3_d") for s in ("p10", "p50", "p90"))
    vfilas = [
        _fila(x)
        for x in d.filas(
            f"SELECT mes, {vcols} FROM curvas_tipo WHERE {' AND '.join(preds)} ORDER BY mes", params
        )
    ]
    uptime = float(valorizar.get("uptime", uptime_obs))
    series: dict = {"mio": (petro, gas)}
    for est in ("p10", "p50", "p90"):
        series[f"grupo_{est}"] = _volumenes_curva(vfilas, uptime, ("petroleo_m3_d", "gas_mil_m3_d"), est)
    return _valorizacion(
        d,
        valorizar,
        series=series,
        mes0=mes0,
        modo_default="historico",
        notas_extra=[
            f"mio = mis volúmenes mensuales reales; grupo_p10/p50/p90 = tasa publicada × {VZ.DIAS_MES:.2f} d × uptime {uptime:.3f} ({'observado en mi pozo' if 'uptime' not in valorizar else 'dado'})",
            f"mes0 = {mes0} (mi primer mes con producción); el grupo se valoriza en los mismos meses calendario",
        ],
    )


def comparar_mi_campania(
    d: Datos,
    filtros: dict | None = None,
    metrica: str = "ip90_petroleo_m3_d_por_m",
    cohorte_ref: int | None = None,
    incluye_outliers: bool = True,
    valorizar: dict | None = None,
) -> dict:
    """Mis pozos (filtros: campania, formacion, cohorte, ventana, siglas) contra sus grupos públicos, pozo por
    pozo: mi valor de la métrica, la mediana pública de su cohorte × formación × ventana, el cociente y el
    porcentaje de pozos públicos que supero; y el resumen de la campaña (mediana mía, mediana de medianas públicas,
    cuántos pozos superan la mediana pública, distribución de posiciones). Métricas: las de indicadores (ip*, acum*,
    gor*, corte_agua*, rama_m, etapas, *_por_m). Requiere cargar_mis_pozos antes. Con valorizar = {modo: historico
    (por defecto) | flat | ultimo, precio_flat?, tasa_anual?, regalia?, region_petroleo?, region_gas?} agrega el
    bloque usd: ingreso bruto de los primeros 12 meses de cada pozo mío (petróleo + gas) y su VAN, el total de la
    campaña, y la mediana pública del acumulado 12 meses del grupo valorizada al mismo precio."""
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
    r = _redondear(r)
    if valorizar is not None:
        r["usd"] = _usd_mi_campania(d, mis, r, valorizar, cohorte_ref, incluye_outliers)
        if r["usd"] and "sin_dato_porque" in r["usd"]:
            notas.append("usd: " + r["usd"]["sin_dato_porque"])
        elif r["usd"]:
            notas.append("usd: " + VZ.NOTA_BRUTO)
    return _envolver(
        r,
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


MESES_USD_CAMPANIA = 12


def _usd_mi_campania(
    d: Datos, mis: P.MisPozos, r: dict, valorizar: dict, cohorte_ref: int | None, incluye_outliers: bool
) -> dict | None:
    """The ``usd`` block of comparar_mi_campania: each well's first 12 months in USD, the campaign total, and the
    public median 12-month cumulative of each well's group valued at the same average price."""
    pozos_usd = []
    bloque: dict | None = None
    for fila in r["pozos"]:
        petro, gas, mes0, _ = _mi_serie_volumenes(mis, fila["sigla"], MESES_USD_CAMPANIA - 1)
        if not petro and not gas:
            pozos_usd.append({"sigla": fila["sigla"], "sin_dato_porque": "sin meses con producción"})
            continue
        b = _valorizacion(d, valorizar, series={"mio": (petro, gas)}, mes0=mes0, modo_default="historico")
        if b is None or "sin_dato_porque" in b:
            return b
        bloque = b
        mio = b["mio"]
        p = {
            "sigla": fila["sigla"],
            "campania": fila.get("campania"),
            "mes0": mes0,
            "meses_valorizados": mio["total"]["meses"],
            "ingreso_usd": mio["total"]["ingreso_usd"],
            "bruto_usd": mio["total"]["bruto_usd"],
            "van_usd": mio["total"]["van_usd"],
        }
        # the public median of acum12 oil and gas of the well's group, at the average price my months used
        if fila.get("grupo") and d.tiene("indicadores", "acum12_petroleo_m3"):
            nivel, resto = fila["grupo"].split(":", 1)
            partes = resto.split("/")
            preds = ["en_alcance", "cohorte = ?", "formacion = ?", "acum12_petroleo_m3 IS NOT NULL"]
            params: list = [int(partes[0]), partes[1]]
            if len(partes) > 2:
                preds.append("ventana = ?")
                params.append(partes[2])
            if not incluye_outliers:
                preds.append("NOT coalesce(outlier_ip90_m, false)")
            gas_col = "median(acum12_gas_mil_m3)" if d.tiene("indicadores", "acum12_gas_mil_m3") else "NULL"
            med = d.con.execute(
                f"SELECT median(acum12_petroleo_m3), {gas_col}, count(*) FROM indicadores WHERE {' AND '.join(preds)}",
                params,
            ).fetchone()
            pp = (
                (mio["precios"]["petroleo"] or {}).get("promedio_usado")
                or (mio["precios"]["petroleo"] or {}).get("ultimo_precio")
                or (mio["precios"]["petroleo"] or {}).get("precio")
            )
            pg = (
                (mio["precios"]["gas"] or {}).get("promedio_usado")
                or (mio["precios"]["gas"] or {}).get("ultimo_precio")
                or (mio["precios"]["gas"] or {}).get("precio")
            )
            if med and med[2] >= N_MIN and med[0] is not None and pp is not None:
                pub = float(med[0]) * float(pp) + (
                    float(med[1]) * float(pg) if (med[1] is not None and pg is not None) else 0.0
                )
                pub *= 1.0 - float(b["regalia"])
                p["mediana_publica_acum12_usd"] = pub
                p["n_publico"] = int(med[2])
                p["ratio_vs_mediana_usd"] = p["ingreso_usd"] / pub if pub else None
            else:
                p["mediana_publica_acum12_usd"] = None
                p["sin_dato_porque"] = (
                    f"grupo público con menos de {N_MIN} pozos con acum12 (ADR-017)"
                    if med and med[2] < N_MIN
                    else "sin acum12 público o sin precio"
                )
        pozos_usd.append(p)
    if bloque is None:
        return {"sin_dato_porque": "ningún pozo mío tiene meses con producción"}
    con = [p for p in pozos_usd if p.get("ingreso_usd") is not None]
    ratios = [p["ratio_vs_mediana_usd"] for p in con if p.get("ratio_vs_mediana_usd") is not None]
    out = {
        "modo": bloque["modo"],
        "tasa_anual": bloque["tasa_anual"],
        "regalia": bloque["regalia"],
        "meses_por_pozo": MESES_USD_CAMPANIA,
        "pozos": pozos_usd,
        "resumen": {
            "n_pozos": len(con),
            "ingreso_usd_total": sum(p["ingreso_usd"] for p in con),
            "van_usd_total": sum(p["van_usd"] for p in con),
            "mediana_ingreso_usd": float(np.median([p["ingreso_usd"] for p in con])) if con else None,
            "mediana_publica_usd": float(
                np.median(
                    [
                        p["mediana_publica_acum12_usd"]
                        for p in con
                        if p.get("mediana_publica_acum12_usd") is not None
                    ]
                )
            )
            if ratios
            else None,
            "ratio_mediano_usd": float(np.median(ratios)) if ratios else None,
            "pozos_sobre_mediana_publica_usd": sum(1 for x in ratios if x > 1),
        },
        "cita": bloque["cita"],
        "notas": bloque["notas"]
        + [
            f"cada pozo mío: ingreso de sus primeros {MESES_USD_CAMPANIA} meses (mes0 = su primer mes con producción); el VAN de cada pozo descuenta desde su propio mes 0",
            "mediana_publica_acum12_usd = mediana del acum12 público de petróleo y gas del grupo × el precio promedio que usó mi pozo (la serie mensual pública no está publicada, ADR-022)",
        ],
    }
    return _redondear(out)


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


def vecinos_de_mis_pozos(
    d: Datos,
    radio_km: float = 10.0,
    filtros: dict | None = None,
    metrica: str = "ip90_petroleo_m3_d_por_m",
    max_vecinos: int = 300,
    incluye_outliers: bool = True,
) -> dict:
    """Mis pozos con coordenadas y los pozos públicos en alcance a menos de radio_km de alguno de ellos (distancia
    haversine sobre las coordenadas publicadas, de superficie), con la métrica elegida para los dos lados: por cada
    pozo mío su valor, la mediana de sus vecinos, el cociente, cuántos vecinos y el más cercano; la lista de vecinos
    con operadora, formación, cohorte, ventana, rama y distancia; y el resumen. filtros como en comparar_mi_campania.
    Es la base del mapa (MCP App). Requiere cargar_mis_pozos antes."""
    mis = _mis(d)
    _check_metrica(d, metrica)
    if metrica not in mis.indicadores.columns:
        raise ErrorHerramienta(f"métrica {metrica!r} no está en mis indicadores")
    radio_km = float(radio_km)
    if not (0.1 <= radio_km <= 100):
        raise ErrorHerramienta("radio_km debe estar entre 0.1 y 100")
    max_vecinos = max(1, min(int(max_vecinos), 2000))
    try:
        sel = K._seleccionar(mis, filtros)
    except K.ErrorComparacion as e:
        raise ErrorHerramienta(str(e)) from e
    con_xy = sel[sel.longitud.notna() & sel.latitud.notna()]
    sin_xy = int(len(sel) - len(con_xy))
    if con_xy.empty:
        raise ErrorHerramienta(
            "ninguno de mis pozos seleccionados tiene longitud y latitud; el mapa necesita coordenadas"
        )
    if not (d.tiene("pozos", "longitud") and d.tiene("pozos", "latitud")):
        raise ErrorHerramienta(f"la fuente {d.fuente} no trae pozos.longitud/latitud")
    preds = ["i.en_alcance", "p.longitud IS NOT NULL", "p.latitud IS NOT NULL"]
    if not incluye_outliers:
        preds.append("coalesce(i.outlier_ip90_m, false) = false")
    pub = d.df(
        f"SELECT p.sigla, p.sigla_clave, p.longitud, p.latitud, i.operadora, i.formacion, i.cohorte, i.ventana, i.rama_m, i.{metrica} AS valor "
        f"FROM pozos p JOIN indicadores i USING (sigla_clave) WHERE {' AND '.join(preds)}"
    )
    lat0 = np.radians(pub.latitud.to_numpy(dtype=float))
    lon0 = np.radians(pub.longitud.to_numpy(dtype=float))
    mios_out: list[dict] = []
    vecinos: dict[int, dict] = {}
    for _, m in con_xy.iterrows():
        la, lo = math.radians(float(m.latitud)), math.radians(float(m.longitud))
        a = np.sin((lat0 - la) / 2) ** 2 + np.cos(la) * np.cos(lat0) * np.sin((lon0 - lo) / 2) ** 2
        dist = 2 * 6371.0 * np.arcsin(np.sqrt(a))
        idx = np.where(dist <= radio_km)[0]
        vals = pub.valor.to_numpy(dtype=float)[idx]
        vals = vals[np.isfinite(vals)]
        vmio = m.get(metrica)
        vmio = None if vmio is None or pd.isna(vmio) else float(vmio)
        med = float(np.median(vals)) if vals.size >= N_MIN else None
        cercano = int(idx[np.argmin(dist[idx])]) if idx.size else None
        mios_out.append(
            {
                "sigla": m.sigla,
                "campania": m.get("campania"),
                "cohorte": None if pd.isna(m.get("cohorte")) else int(m.cohorte),
                "ventana": m.get("ventana") if isinstance(m.get("ventana"), str) else None,
                "rama_m": None if pd.isna(m.get("rama_m")) else float(m.rama_m),
                "longitud": float(m.longitud),
                "latitud": float(m.latitud),
                "valor": vmio,
                "n_vecinos": int(idx.size),
                "n_vecinos_con_dato": int(vals.size),
                "mediana_vecinos": med,
                "ratio_vecinos": (vmio / med) if (vmio is not None and med) else None,
                "vecino_mas_cercano": pub.sigla.iloc[cercano] if cercano is not None else None,
                "distancia_min_km": float(dist[cercano]) if cercano is not None else None,
                "sin_dato_porque": None
                if med is not None
                else f"menos de {N_MIN} vecinos con {metrica} (ADR-017)",
            }
        )
        for j in idx:
            j = int(j)
            if j not in vecinos or dist[j] < vecinos[j]["distancia_km"]:
                r = pub.iloc[j]
                vecinos[j] = {
                    "sigla": r.sigla,
                    "sigla_clave": r.sigla_clave,
                    "operadora": r.operadora,
                    "formacion": r.formacion,
                    "cohorte": None if pd.isna(r.cohorte) else int(r.cohorte),
                    "ventana": r.ventana,
                    "rama_m": None if pd.isna(r.rama_m) else float(r.rama_m),
                    "longitud": float(r.longitud),
                    "latitud": float(r.latitud),
                    "valor": None if pd.isna(r.valor) else float(r.valor),
                    "distancia_km": float(dist[j]),
                    "mio_mas_cercano": m.sigla,
                }
    lista = sorted(vecinos.values(), key=lambda v: v["distancia_km"])
    cortado = len(lista) > max_vecinos
    lista = lista[:max_vecinos]
    vmios = [x["valor"] for x in mios_out if x["valor"] is not None]
    vvec = [v["valor"] for v in vecinos.values() if v["valor"] is not None]
    resumen = {
        "mediana_mia": float(np.median(vmios)) if vmios else None,
        "mediana_vecinos": float(np.median(vvec)) if len(vvec) >= N_MIN else None,
        "ratio": None,
        "operadoras": sorted({v["operadora"] for v in vecinos.values() if v["operadora"]}),
        "cohortes": sorted({v["cohorte"] for v in vecinos.values() if v["cohorte"] is not None}),
    }
    if resumen["mediana_mia"] is not None and resumen["mediana_vecinos"]:
        resumen["ratio"] = resumen["mediana_mia"] / resumen["mediana_vecinos"]
    exclusiones = []
    if sin_xy:
        exclusiones.append(f"{sin_xy} pozo(s) míos sin coordenadas no entran")
    if not incluye_outliers:
        exclusiones.append("pozos públicos con outlier_ip90_m = True excluidos (ADR-018)")
    if cortado:
        exclusiones.append(f"más de {max_vecinos} vecinos: se listan los {max_vecinos} más cercanos")
    notas = _notas_propios(mis) + [
        "coordenadas publicadas de superficie (Capítulo IV), no de la rama; la distancia es haversine en km",
        "los vecinos mezclan cohortes y ventanas: la mediana de vecinos es contexto geográfico, no una curva tipo",
    ]
    datos = {
        "metrica": metrica,
        "unidad": METRICAS[metrica],
        "radio_km": radio_km,
        "n_mios": len(mios_out),
        "n_vecinos": len(vecinos),
        "resumen": resumen,
        "mios": mios_out[:MAX_FILAS],
        "vecinos": lista,
    }
    return _envolver(
        _redondear(datos),
        d=d,
        tabla="mis_indicadores (sesión) × pozos + indicadores",
        columnas=["longitud", "latitud", metrica, "operadora", "formacion", "cohorte", "ventana", "rama_m"],
        filtros={
            "radio_km": radio_km,
            "filtros": filtros or {},
            "metrica": metrica,
            "incluye_outliers": incluye_outliers,
        },
        regla_doc=f"{DOC_PROPIOS}#vecinos_de_mis_pozos; docs/maestro.md (coordenadas); ADR-017",
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
    valorizar: dict | None = None,
) -> dict:
    """Ajusta la declinación de un pozo (público por sigla_clave, o mío con mio=true) con Arps exponencial,
    hiperbólico (con declinación terminal d_min_anual), armónico o Duong, elige por AIC si modelo=auto, y
    pronostica hasta horizonte_anios (20 o 30): EUR, EUR restante, acumulado por año, parámetros, y la banda
    P10/P50/P90 del EUR por bootstrap de residuos (n_bootstrap réplicas). Usa la tasa por día efectivo, omite los
    primeros omitir_meses meses (limpieza), integra con el uptime observado (o el dado) y corta en q_min si se
    pasa. El pozo público necesita la fuente parquet y data/raw; si no, usar pronosticar_curva_tipo. No es
    simulación de reservorio. Con valorizar = {modo: historico (por defecto: historia a precio de cada mes, futuro
    al último precio) | flat | ultimo, precio_flat?, tasa_anual?, regalia?, region_petroleo?, region_gas?} agrega
    el bloque usd del pronóstico de la tasa pedida (petróleo o gas; equivalente no se valoriza): USD por mes,
    acumulado y VAN."""
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
    res = _redondear(res)
    if valorizar is not None:
        if tasa == "equivalente_m3_d":
            raise ErrorHerramienta(
                "valorizar: la tasa equivalente_m3_d no se valoriza; pedí petroleo_m3_d o gas_mil_m3_d"
            )
        vol = [float(v) for v in pr.volumen_mes]
        series = {"pronostico": (vol, None) if tasa == "petroleo_m3_d" else (None, vol)}
        provincia = cuenca = None
        if not mio and d.tiene("pozos", "provincia"):
            fila = d.filas("SELECT provincia, cuenca FROM pozos WHERE sigla_clave = ?", [meta["sigla_clave"]])
            if fila:
                provincia, cuenca = fila[0]["provincia"], fila[0]["cuenca"]
        res["usd"] = _valorizacion(
            d,
            valorizar,
            series=series,
            mes0=_mes_str(serie.mes_fecha.iloc[0]) if "mes_fecha" in serie else None,
            provincia=provincia,
            cuenca=cuenca,
            modo_default="historico",
            notas_extra=[
                f"pronostico = volumen mensual del pronóstico P50 ({tasa}): historia observada hasta el mes {int(serie.mes.max())}, después la curva ajustada × {VZ.DIAS_MES:.2f} d × uptime {up:.3f}; la banda bootstrap del EUR no se valoriza"
            ],
        )
        if res["usd"] and "sin_dato_porque" in res["usd"]:
            notas.append("usd: " + res["usd"]["sin_dato_porque"])
        elif res["usd"]:
            notas.append("usd: " + VZ.NOTA_BRUTO)
    return _envolver(
        res,
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
    valorizar: dict | None = None,
) -> dict:
    """Monte Carlo de una campaña de n_pozos pozos nuevos muestreados de la curva tipo publicada de formacion ×
    cohorte_ref (× ventana si se da): cada pozo simulado toma una posición en el grupo y su tasa mes a mes sale de
    los P10/P50/P90 publicados; si se pasa rama_m y el grupo tiene curva por metro, escala por la rama. Los pozos
    entran a ritmo_pozos_por_mes (por defecto todos en el mes 0). Devuelve por mes P10/P50/P90 y media de la tasa
    agregada y del acumulado, pozos en línea, y el acumulado final con banda. La banda es la dispersión publicada
    entre pozos, nada más: sin interferencia, sin instalaciones, sin precio salvo que se pida. No es simulación de
    reservorio. Con valorizar = {modo: ultimo (por defecto: último precio publicado, constante) | flat | historico
    (necesita mes0), precio_flat?, tasa_anual? (0.10), regalia?, mes0?, region_petroleo?, region_gas?} agrega el
    bloque usd: ingreso bruto de la campaña en USD por mes, acumulado y VAN para las bandas P10/P50/P90."""
    _check_tasa_abs(tasa)
    f = _resolver_formacion(d, formacion)
    if f is None:
        raise ErrorHerramienta(f"formación {formacion!r} no existe en indicadores.formacion")
    if cohorte_ref is None:
        (cohorte_ref,) = d.con.execute(
            "SELECT max(cohorte) FROM curvas_tipo WHERE formacion = ? AND nivel = 'cohorte_formacion' AND publicable AND mes >= 23",
            [f],
        ).fetchone()
        if cohorte_ref is None:
            raise ErrorHerramienta(f"ninguna cohorte de {f} tiene 24 meses publicables; pasá cohorte_ref")
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
    r = _redondear(r)
    if valorizar is not None:
        if tasa == "equivalente_m3_d":
            raise ErrorHerramienta(
                "valorizar: la tasa equivalente_m3_d no se valoriza; pedí petroleo_m3_d o gas_mil_m3_d"
            )
        series = {}
        for est in ("p10", "p50", "p90"):
            vol = VZ.volumenes_desde_acumulado(r["acumulado"][est])
            series[est] = (vol, None) if tasa == "petroleo_m3_d" else (None, vol)
        r["usd"] = _valorizacion(
            d,
            valorizar,
            series=series,
            modo_default="ultimo",
            notas_extra=[
                f"p10/p50/p90 = la banda del acumulado de la campaña ({tasa}) convertida a volumen mensual; modo historico necesita valorizar.mes0 (mes calendario del mes 0 de la campaña)"
            ],
        )
        if r["usd"] and "sin_dato_porque" in r["usd"]:
            notas.append("usd: " + r["usd"]["sin_dato_porque"])
        elif r["usd"]:
            notas.append("usd: " + VZ.NOTA_BRUTO)
    return _envolver(
        r,
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


# --- F6: public prices and the USD block (ADR-034, ADR-035) ---------------------------------------------------------

DOC_PRECIOS = "docs/precios.md"
MAX_MESES_PRECIOS = 240
_VALORIZAR_CLAVES = (
    "modo",
    "precio_flat",
    "tasa_anual",
    "regalia",
    "mes0",
    "region_petroleo",
    "region_gas",
    "segmento_gas",
    "contrato_gas",
    "uptime",
)
_SIN_PRECIOS = (
    "tabla precios vacía en esta fuente: corré `python pipeline.py download regalias_crudo precios_gas` y "
    "`python pipeline.py precios`, o usá valorizar.modo = 'flat' con precio_flat (docs/precios.md)"
)


def _regiones_precios(d: Datos, producto: str) -> list[str]:
    return [
        r
        for (r,) in d.con.execute(
            "SELECT DISTINCT region FROM precios WHERE producto = ? ORDER BY 1", [producto]
        ).fetchall()
    ]


def _serie_precio(
    d: Datos, producto: str, region: str, segmento: str | None = None, contrato: str | None = None
) -> VZ.SeriePrecio:
    """The monthly price series of one product in one region from the ``precios`` table, in the volume unit."""
    if producto == "petroleo":
        segmento = segmento or SEGMENTO_PETROLEO
        preds, params = ["producto = 'petroleo'", "region = ?", "segmento = ?"], [region, segmento]
        col, unidad = "precio_usd_m3", "USD/m³"
    else:
        segmento = segmento or SEGMENTO_GAS_DEFAULT
        contrato = contrato or CONTRATO_GAS_DEFAULT
        preds, params = (
            ["producto = 'gas'", "region = ?", "segmento = ?", "contrato = ?"],
            [region, segmento, contrato],
        )
        col, unidad = "precio_usd_mil_m3", "USD/mil m³"
    filas = d.filas(
        f"SELECT anio, mes, {col} AS p, provisorio, fuente FROM precios WHERE {' AND '.join(preds)} AND {col} IS NOT NULL ORDER BY anio, mes",
        params,
    )
    s = VZ.SeriePrecio(
        producto,
        region,
        unidad,
        {},
        filas[0]["fuente"] if filas else "",
        segmento,
        contrato if producto == "gas" else None,
    )
    for f in filas:
        k = f"{int(f['anio']):04d}-{int(f['mes']):02d}"
        s.por_mes[k] = float(f["p"])
        if f.get("provisorio"):
            s.provisorios.add(k)
    return s


def _resolver_region(
    d: Datos, producto: str, pedida: str | None, del_pozo: str | None, provincia: str | None = None
) -> tuple[str, list[str]]:
    """The table's region for a product: the one asked for, else the well's, else the default; with the reason."""
    canon = (
        provincia_canonica if producto == "petroleo" else (lambda c, p=provincia: cuenca_gas_canonica(c, p))
    )
    default = REGION_PETROLEO_DEFAULT if producto == "petroleo" else REGION_GAS_DEFAULT
    nombre = "provincia" if producto == "petroleo" else "cuenca"
    disponibles = _regiones_precios(d, producto)
    notas: list[str] = []
    if pedida:
        r = canon(pedida)
        if r is None or (disponibles and r not in disponibles):
            raise ErrorHerramienta(
                f"valorizar.region_{producto}: {pedida!r} no está en la tabla precios; las regiones de {producto} son {', '.join(disponibles) or '(tabla vacía)'}"
            )
        return r, notas
    r = canon(del_pozo) if del_pozo else None
    if r is not None and (not disponibles or r in disponibles):
        return r, notas
    if del_pozo:
        notas.append(
            f"{producto}: la {nombre} del pozo ({del_pozo}) no tiene precio publicado; se usa {default} (ADR-035)"
        )
    else:
        notas.append(
            f"{producto}: sin {nombre} conocida; se usa el precio de {default} (ADR-035); valorizar.region_{producto} lo cambia"
        )
    return default, notas


def _valorizacion(
    d: Datos,
    params: dict | None,
    *,
    series: dict[str, tuple[list | None, list | None]],
    mes0: str | None = None,
    provincia: str | None = None,
    cuenca: str | None = None,
    modo_default: str = "ultimo",
    notas_extra: list[str] | None = None,
) -> dict | None:
    """The ``usd`` block a tool attaches when it was called with ``valorizar``: one valuation per entry of
    ``series`` (label -> (oil m³ per month, gas mil m³ per month)), the resolved regions and prices, a citation to
    the ``precios`` table and the caveats. Never raises for a missing table (``sin_dato_porque`` instead); raises
    :class:`ErrorHerramienta` when the request itself is wrong."""
    if params is None:
        return None
    p = dict(params or {})
    extra = set(p) - set(_VALORIZAR_CLAVES)
    if extra:
        raise ErrorHerramienta(
            f"valorizar: claves desconocidas {sorted(extra)}; las válidas son {', '.join(_VALORIZAR_CLAVES)}"
        )
    modo = p.get("modo") or modo_default
    if modo not in VZ.MODOS:
        raise ErrorHerramienta(f"valorizar.modo debe ser uno de {', '.join(VZ.MODOS)}; recibí {modo!r}")
    try:
        mes0 = VZ.validar_mes(p.get("mes0")) if p.get("mes0") else mes0
    except VZ.ErrorValorizacion as e:
        raise ErrorHerramienta(f"valorizar: {e}") from e
    tasa = float(p.get("tasa_anual", VZ.TASA_ANUAL_DEFAULT))
    regalia = float(p.get("regalia", 0.0))
    notas = list(notas_extra or [])
    hay_petro = any(v[0] is not None for v in series.values())
    hay_gas = any(v[1] is not None for v in series.values())
    sp = sg = None
    cita_filtros: dict = {"modo": modo, "tasa_anual": tasa, "regalia": regalia, "mes0": mes0}
    if modo != "flat":
        if not d.tiene_precios():
            return {"sin_dato_porque": _SIN_PRECIOS, "modo": modo}
        if hay_petro:
            region, n = _resolver_region(d, "petroleo", p.get("region_petroleo"), provincia)
            notas += n
            sp = _serie_precio(d, "petroleo", region)
            cita_filtros["petroleo"] = {"region": region, "segmento": SEGMENTO_PETROLEO}
        if hay_gas:
            region, n = _resolver_region(d, "gas", p.get("region_gas"), cuenca, provincia)
            notas += n
            seg = p.get("segmento_gas") or SEGMENTO_GAS_DEFAULT
            con = p.get("contrato_gas") or CONTRATO_GAS_DEFAULT
            if seg not in SEGMENTOS_GAS or con not in CONTRATOS_GAS:
                raise ErrorHerramienta(
                    f"valorizar.segmento_gas ∈ {', '.join(SEGMENTOS_GAS)}; contrato_gas ∈ {', '.join(CONTRATOS_GAS)}"
                )
            sg = _serie_precio(d, "gas", region, seg, con)
            cita_filtros["gas"] = {"region": region, "segmento": seg, "contrato": con}
    else:
        cita_filtros["precio_flat"] = p.get("precio_flat")
    out: dict = {"modo": modo, "mes0": mes0, "tasa_anual": tasa, "regalia": regalia}
    try:
        for etiqueta, (petro, gas) in series.items():
            out[etiqueta] = VZ.valorizar(
                petro,
                gas,
                modo=modo,
                precio_petroleo=sp,
                precio_gas=sg,
                mes0=mes0,
                flat=p.get("precio_flat"),
                tasa_anual=tasa,
                regalia=regalia,
                compacto=True,
            )
    except VZ.ErrorValorizacion as e:
        raise ErrorHerramienta(f"valorizar: {e}") from e
    primero = next(iter(series))
    out["notas"] = notas + out[primero]["notas"]
    for etiqueta in series:
        out[etiqueta].pop("notas", None)  # the same caveats once, at the block level
    out["cita"] = {
        "tabla": "precios" if modo != "flat" else "precio_flat (del usuario)",
        "columnas": ["producto", "region", "anio", "mes", "precio_usd_m3", "precio_usd_mil_m3", "provisorio"],
        "filtros": {k: v for k, v in cita_filtros.items() if v is not None},
        "regla_doc": f"{DOC_PRECIOS}; ADR-034, ADR-035",
    }
    return _redondear(out)


def _volumenes_curva(
    filas: list[dict], uptime: float, claves: tuple[str, str], est: str
) -> tuple[list, list]:
    """Oil and gas volumes per month from a type curve's rows (``<col>_<est>`` producing-day rates)."""
    petro = VZ.volumenes_desde_tasas([f.get(f"{claves[0]}_{est}") for f in filas], uptime)
    gas = VZ.volumenes_desde_tasas([f.get(f"{claves[1]}_{est}") for f in filas], uptime)
    return petro, gas


def _mes_str(ts: Any) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).strftime("%Y-%m")


def precios(
    d: Datos,
    producto: str,
    region: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    segmento: str | None = None,
    contrato: str | None = None,
) -> dict:
    """Precios públicos mensuales (tabla precios, docs/precios.md): petroleo = precio promedio realizado del crudo
    en USD/m³ por provincia (regalías, Secretaría de Energía; región por defecto Neuquén); gas = USD/MMBTU por
    cuenca, segmento (ppp por defecto: promedio ponderado; distribuidora, gnc, usina, industria, otros, expo) y
    contrato (total por defecto; firme, interrumpible), con la conversión a USD por mil m³ a 9.300 kcal/m³
    (región por defecto Neuquina). desde/hasta 'YYYY-MM' (por defecto los últimos 24 meses). Devuelve también las
    regiones disponibles, el último mes publicado y si el precio es provisorio. Los precios son los que se pueden
    citar para valorizar en dólares (parámetro valorizar de curva_tipo, comparar_mi_pozo, simular_campania…)."""
    if producto not in ("petroleo", "gas"):
        raise ErrorHerramienta("producto debe ser petroleo o gas")
    if not d.tiene_precios():
        return _envolver(
            {"producto": producto, "meses": [], "sin_dato_porque": _SIN_PRECIOS},
            d=d,
            tabla="precios",
            columnas=["producto", "region", "anio", "mes", "precio_dataset"],
            filtros={"producto": producto},
            regla_doc=f"{DOC_PRECIOS}; ADR-034",
            notas=["la tabla precios no está publicada en esta fuente"],
        )
    region_c, notas_r = _resolver_region(d, producto, region, None)
    if producto == "gas":
        segmento = segmento or SEGMENTO_GAS_DEFAULT
        contrato = contrato or CONTRATO_GAS_DEFAULT
        if segmento not in SEGMENTOS_GAS:
            raise ErrorHerramienta(f"segmento debe ser uno de {', '.join(SEGMENTOS_GAS)}")
        if contrato not in CONTRATOS_GAS:
            raise ErrorHerramienta(f"contrato debe ser uno de {', '.join(CONTRATOS_GAS)}")
    else:
        segmento = SEGMENTO_PETROLEO
        contrato = None
    try:
        desde = VZ.validar_mes(desde, "desde")
        hasta = VZ.validar_mes(hasta, "hasta")
    except VZ.ErrorValorizacion as e:
        raise ErrorHerramienta(str(e)) from e
    preds = ["producto = ?", "region = ?", "segmento = ?"]
    params: list = [producto, region_c, segmento]
    if contrato:
        preds.append("contrato = ?")
        params.append(contrato)
    (ultimo,) = d.con.execute(
        f"SELECT max(anio * 100 + mes) FROM precios WHERE {' AND '.join(preds)} AND precio_dataset IS NOT NULL",
        params,
    ).fetchone()
    ultimo_mes = f"{ultimo // 100:04d}-{ultimo % 100:02d}" if ultimo else None
    if hasta is None:
        hasta = ultimo_mes or "9999-12"
    if desde is None:
        desde = VZ.mes_mas(hasta, -23) if hasta != "9999-12" else "0000-01"
    preds.append("anio * 100 + mes BETWEEN ? AND ?")
    params += [int(desde[:4]) * 100 + int(desde[5:]), int(hasta[:4]) * 100 + int(hasta[5:])]
    filas = d.filas(
        "SELECT anio, mes, precio_dataset, precio_usd_m3, precio_usd_mil_m3, provisorio, produccion_m3, regalias_usd "
        f"FROM precios WHERE {' AND '.join(preds)} ORDER BY anio, mes",
        params,
    )
    meses = []
    for f in filas:
        fila = {
            "mes": f"{int(f['anio']):04d}-{int(f['mes']):02d}",
            "precio_dataset": _sig(f["precio_dataset"]),
            "precio_usd_m3": _sig(f["precio_usd_m3"]),
            "precio_usd_mil_m3": _sig(f["precio_usd_mil_m3"]),
            "provisorio": bool(f["provisorio"]),
        }
        if producto == "petroleo":
            fila["produccion_m3"] = _sig(f["produccion_m3"])
            fila["regalias_usd"] = _sig(f["regalias_usd"])
        meses.append(fila)
    cortado = len(meses) > MAX_MESES_PRECIOS
    meses = meses[-MAX_MESES_PRECIOS:]
    con_precio = [m["precio_dataset"] for m in meses if m["precio_dataset"] is not None]
    datos = {
        "producto": producto,
        "region": region_c,
        "segmento": segmento,
        "contrato": contrato,
        "unidad_dataset": "USD/m³" if producto == "petroleo" else "USD/MMBTU",
        "desde": desde,
        "hasta": hasta,
        "ultimo_mes_publicado": ultimo_mes,
        "n_meses": len(meses),
        "resumen": {
            "ultimo": con_precio[-1] if con_precio else None,
            "promedio": _sig(sum(con_precio) / len(con_precio)) if con_precio else None,
            "min": min(con_precio) if con_precio else None,
            "max": max(con_precio) if con_precio else None,
        },
        "regiones_disponibles": _regiones_precios(d, producto),
        "meses": meses,
    }
    if producto == "gas":
        datos["mmbtu_por_mil_m3"] = _sig(VZ.units.MMBTU_PER_THOUSAND_M3)
    notas = notas_r + [
        "petróleo: precio promedio de venta realizado que informan las provincias para liquidar regalías (USD/m³); los dos últimos meses son provisorios"
        if producto == "petroleo"
        else VZ.NOTA_GAS + "; ppp = promedio ponderado de los segmentos; total = firme + interrumpible",
    ]
    if not meses:
        notas.append("ningún mes con precio en ese rango y región")
    if cortado:
        notas.append(f"se muestran los últimos {MAX_MESES_PRECIOS} meses; acotá desde/hasta")
    if d.fuente == "json":
        notas.append("fuente json: petróleo desde 2006 y gas sólo contrato total (ADR-034)")
    return _envolver(
        datos,
        d=d,
        tabla="precios",
        columnas=[
            "producto",
            "region",
            "segmento",
            "contrato",
            "anio",
            "mes",
            "precio_dataset",
            "precio_usd_m3",
            "precio_usd_mil_m3",
            "provisorio",
        ],
        filtros={
            "producto": producto,
            "region": region_c,
            "segmento": segmento,
            "contrato": contrato,
            "desde": desde,
            "hasta": hasta,
        },
        regla_doc=f"{DOC_PRECIOS}; ADR-034",
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
    fuera = refs - set(TODAS) - ctes
    if fuera:
        raise ErrorHerramienta(
            f"tablas fuera de la allowlist: {', '.join(sorted(fuera))}; permitidas: {', '.join(TODAS)}"
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


_NUM = {"type": "number"}
_VALORIZAR_SCHEMA = {
    "type": "object",
    "description": (
        "F6: agrega el bloque usd (ingreso bruto por mes, acumulado y VAN a precios públicos, docs/precios.md). "
        "modo: historico (precio del mes calendario) | flat (precio_flat) | ultimo (último publicado)"
    ),
    "properties": {
        "modo": {"type": "string", "enum": list(VZ.MODOS)},
        "precio_flat": {
            "type": "object",
            "properties": {
                "petroleo_usd_m3": _NUM,
                "petroleo_usd_bbl": _NUM,
                "gas_usd_mil_m3": _NUM,
                "gas_usd_mmbtu": _NUM,
            },
            "additionalProperties": False,
        },
        "tasa_anual": {"type": "number", "description": "tasa de descuento anual, fracción (0.10)"},
        "regalia": {
            "type": "number",
            "description": "fracción a restar del bruto (0; 0.12 es la alícuota base)",
        },
        "mes0": {"type": "string", "description": "YYYY-MM del mes 0 (modo historico)"},
        "region_petroleo": {
            "type": "string",
            "description": "provincia de la tabla precios (Neuquén por defecto)",
        },
        "region_gas": {"type": "string", "description": "cuenca de la tabla precios (Neuquina por defecto)"},
        "segmento_gas": {"type": "string", "enum": list(SEGMENTOS_GAS)},
        "contrato_gas": {"type": "string", "enum": list(CONTRATOS_GAS)},
        "uptime": {
            "type": "number",
            "description": "días efectivos / calendario para convertir tasas de curva a volumen (0.92)",
        },
    },
    "additionalProperties": False,
}

HERRAMIENTAS: dict[str, dict] = {
    "metadatos": {"fn": metadatos, "schema": _schema({}, [])},
    "describir_tabla": {
        "fn": describir_tabla,
        "schema": _schema({"tabla": {"type": "string", "enum": list(TODAS)}}, ["tabla"]),
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
                "valorizar": _VALORIZAR_SCHEMA,
            },
            ["nivel", "claves"],
        ),
    },
    "precios": {
        "fn": precios,
        "schema": _schema(
            {
                "producto": {"type": "string", "enum": ["petroleo", "gas"]},
                "region": {
                    "type": "string",
                    "description": "provincia (petróleo) o cuenca (gas) de la tabla precios",
                },
                "desde": {"type": "string", "description": "YYYY-MM"},
                "hasta": {"type": "string", "description": "YYYY-MM"},
                "segmento": {"type": "string", "enum": list(SEGMENTOS_GAS)},
                "contrato": {"type": "string", "enum": list(CONTRATOS_GAS)},
            },
            ["producto"],
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
                    "valorizar": _VALORIZAR_SCHEMA,
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
                    "valorizar": _VALORIZAR_SCHEMA,
                },
                [],
            ),
        },
        "vecinos_de_mis_pozos": {
            "fn": vecinos_de_mis_pozos,
            "schema": _schema(
                {
                    "radio_km": {"type": "number"},
                    "filtros": _FILTROS_MIOS_SCHEMA,
                    "metrica": {"type": "string", "enum": sorted(METRICAS)},
                    "max_vecinos": _INT,
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
                    "valorizar": _VALORIZAR_SCHEMA,
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
                    "valorizar": _VALORIZAR_SCHEMA,
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
