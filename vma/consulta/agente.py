"""The question-answering loop (ADR-025, ADR-028).

A *proveedor* turns (system, messages, tools) into one assistant message in the Claude API shape; the loop
runs the tools the message asks for, appends the results, and repeats until the model answers in text. Two
providers: :class:`ProveedorAnthropic` (Claude through the official SDK, streaming, adaptive thinking) and
:class:`ProveedorMock`, a model-free planner that picks tools from keywords and writes an answer from their
results, so the whole path (tools -> loop -> validator -> transcript) runs in tests and in CI without a key.

Every text answer goes through :func:`vma.consulta.validador.validar`: a number that no tool returned sends the
model one correction message; a second failure is shown with a warning, never silently.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from vma.consulta import herramientas as H
from vma.consulta.datos import Datos
from vma.consulta.validador import Validacion, validar

MODELO_DEFAULT = "claude-opus-5-5"
ESFUERZO_DEFAULT = "medium"
MAX_TURNOS = 12
MAX_TOKENS = 16000

SYSTEM = """Sos el asistente del observatorio abierto de Vaca Muerta: respondés preguntas sobre las tablas publicadas
(pozos, indicadores, curvas_tipo, precios) que salen de los datos públicos por pozo de la Secretaría de Energía de
Argentina (Capítulo IV). Hablás en castellano rioplatense, técnico y directo, como un ingeniero de reservorios.

Reglas, en orden de importancia:

1. **Sin cita no hay número.** Cada número que escribís sale de un resultado de herramienta de esta conversación
   y va acompañado de su cita: tabla.columna y el filtro aplicado (por ejemplo: "mediana 0,062 m³/d por m
   [indicadores.ip90_petroleo_m3_d_por_m; formacion = Vaca Muerta, ventana = petroleo, cohorte = 2024, n = 48]").
   No calculés promedios, porcentajes, diferencias ni totales que la herramienta no devolvió; si hace falta, pedí
   otra herramienta o decí que no está calculado. No redondeés más allá de 2-3 cifras significativas.
2. **Sin dato porque…** Cuando un indicador es nulo, decís el motivo que trae el resultado (`sin_dato_porque`,
   `exclusiones`, flags) y nunca lo reemplazás por cero ni lo inventás.
3. **Días efectivos vs calendario.** Las tasas (IP30/90/180, curvas tipo) son por día efectivo de producción, no
   por día calendario; los acumulados son por meses calendario. Aclaralo la primera vez que das una tasa.
4. **Contexto honesto.** Repetí el `n` de cada estadístico; marcá como débil lo que tenga n < 5 o esté en
   `grupos_chicos`; si la herramienta advierte que mezcla ventanas o formaciones, decilo o filtrá mejor.
5. **No inventás.** Si las herramientas no alcanzan para responder, decís qué falta y qué sí se puede responder.
   No conocés nada de la cuenca que no esté en las tablas; opiniones de la industria, no.
6. Flujo típico: para un pozo, `buscar_pozo` y después `ficha_pozo`; para comparar operadoras/ventanas/cohortes
   de una formación, `comparar_grupo` o `ranking` (filtrá por ventana para comparar pares); para la evolución
   mensual, `curva_tipo`; si no conocés una columna, `describir_tabla`; para fechar la respuesta, `metadatos`.
   Las operadoras son filas del dataset público y se tratan todas igual.
7. **Plata.** `precios` da el precio público del crudo (USD/m³ por provincia) y del gas (USD/MMBTU por cuenca);
   el parámetro `valorizar` de `curva_tipo`, `comparar_mi_pozo`, `comparar_mi_campania`, `pronosticar_pozo` y
   `simular_campania` agrega el bloque `usd`. Siempre decís que es ingreso BRUTO (sin capex, opex ni impuestos;
   regalías sólo si se pidió `regalia`), qué modo de precio y qué región se usó, y citás la tabla `precios`.

Terminá con una línea "Datos: descargados el <fecha_datos>, maestro <version_maestro>, fuente <fuente>" tomada de
cualquier resultado de herramienta."""


# --- messages in the Claude API shape -------------------------------------------------------------------------


@dataclass
class Llamada:
    herramienta: str
    entrada: dict
    salida: Any
    error: bool = False
    segundos: float = 0.0


@dataclass
class Respuesta:
    pregunta: str
    texto: str
    llamadas: list[Llamada] = field(default_factory=list)
    validacion: Validacion | None = None
    reintentos: int = 0
    turnos: int = 0
    proveedor: str = ""
    modelo: str = ""
    uso: dict = field(default_factory=dict)

    def transcript(self) -> dict:
        return {
            "pregunta": self.pregunta,
            "respuesta": self.texto,
            "herramientas": [
                {"herramienta": c.herramienta, "entrada": c.entrada, "error": c.error} for c in self.llamadas
            ],
            "validacion": None if self.validacion is None else self.validacion.mensaje(),
            "reintentos": self.reintentos,
            "turnos": self.turnos,
            "proveedor": self.proveedor,
            "modelo": self.modelo,
            "uso": self.uso,
        }


class Proveedor(Protocol):
    nombre: str
    modelo: str

    def crear(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        """Return ``{"content": [blocks...], "stop_reason": str, "usage": {...}}``."""
        ...


# --- Anthropic ----------------------------------------------------------------------------------------------


class ProveedorAnthropic:
    """Claude through the official SDK: streaming (long answers never hit the HTTP timeout), adaptive thinking,
    effort as the only depth control. Thinking blocks are passed back unchanged (``model_dump``)."""

    nombre = "anthropic"

    def __init__(self, modelo: str = MODELO_DEFAULT, esfuerzo: str = ESFUERZO_DEFAULT, cliente=None):
        if cliente is None:
            import anthropic  # optional dependency: pip install -e ".[agente]"

            cliente = anthropic.Anthropic()
        self.cliente = cliente
        self.modelo = modelo
        self.esfuerzo = esfuerzo

    def crear(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        with self.cliente.messages.stream(
            model=self.modelo,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self.esfuerzo},
        ) as stream:
            msg = stream.get_final_message()
        content = [b.model_dump(exclude_none=True) for b in msg.content]
        uso = msg.usage.model_dump(exclude_none=True) if msg.usage else {}
        return {"content": content, "stop_reason": msg.stop_reason, "usage": uso}


# --- Mock: no model -----------------------------------------------------------------------------------------

_SIGLA = re.compile(
    r"\b[A-Za-z]{1,5}\.[A-Za-z]{2,3}\.[A-Za-z]{1,6}(?:\.\s?[A-Za-z]{1,4})?[-\s]?\d{1,5}(?:\([a-z]{1,2}\))?"
)
_COHORTE = re.compile(r"\b(20[0-3]\d)\b")
_RUTA = re.compile(r"(?:[A-Za-z]:)?[\w./\\-]+\.(?:csv|parquet)\b")
_MIO = re.compile(r"\bMIO-\d{3}\b", re.IGNORECASE)
_VENTANAS = {"petróleo": "petroleo", "petroleo": "petroleo", "gas": "gas", "condensado": "volatil_condensado"}


class ProveedorMock:
    """A scripted stand-in for the model: keyword planning, then an answer written only from tool results.

    ``con_numero_inventado=True`` adds a number no tool returned to the first answer, so the validator's retry
    path can be exercised end to end without a model.
    """

    nombre = "mock"
    modelo = "mock"

    def __init__(self, con_numero_inventado: bool = False):
        self.con_numero_inventado = con_numero_inventado
        self._id = 0

    def _tool_use(self, name: str, entrada: dict) -> dict:
        self._id += 1
        return {"type": "tool_use", "id": f"mock_{self._id}", "name": name, "input": entrada}

    @staticmethod
    def _plan(pregunta: str, tools: list[dict]) -> list[tuple[str, dict]]:
        q = pregunta.lower()
        nombres = {t["name"] for t in tools}
        plan: list[tuple[str, dict]] = []
        sigla = _SIGLA.search(pregunta)
        cohortes = [int(c) for c in _COHORTE.findall(pregunta)]
        ventana = next((v for k, v in _VENTANAS.items() if k in q), None)
        formacion = "Vaca Muerta"
        for f in ("lajas", "mulichinco", "los molles", "punta rosada", "precuyo", "quintuco", "vaca muerta"):
            if f in q:
                formacion = f.title()
        rutas = _RUTA.findall(pregunta)
        mio = _MIO.search(pregunta)
        propios = any(
            w in q for w in ("mis pozos", "mi pozo", "mi campaña", "mi campania", "mis datos", "brecha")
        )
        if rutas and "cargar_mis_pozos" in nombres:
            entrada = {"ruta": rutas[0]}
            if len(rutas) > 1:
                entrada["ruta_pozos"] = rutas[1]
            plan.append(("cargar_mis_pozos", entrada))
        if (propios or mio) and "comparar_mi_pozo" in nombres:
            if "brecha" in q:
                e: dict = {"mes_max": 12}
                if mio:
                    e["sigla"] = mio.group(0).upper()
                elif "pad-" in q:
                    e["filtros"] = {"campania": re.search(r"pad-[a-z]", q).group(0).upper()}
                plan.append(("brechas", e))
            elif any(w in q for w in ("pronóstic", "pronostic", "eur", "declinaci")) and mio:
                plan.append(
                    ("pronosticar_pozo", {"sigla": mio.group(0).upper(), "mio": True, "n_bootstrap": 100})
                )
            elif any(w in q for w in ("campaña", "campania", "ranking")) or ("pad-" in q and not mio):
                f: dict = {}
                m_pad = re.search(r"pad-[a-z]", q)
                if m_pad:
                    f["campania"] = m_pad.group(0).upper()
                if cohortes:
                    f["cohorte"] = cohortes[0]
                plan.append(("comparar_mi_campania", {"filtros": f}))
            elif mio:
                plan.append(("comparar_mi_pozo", {"sigla": mio.group(0).upper(), "mes_max": 12}))
            if plan:
                return plan
        # F6: money. "precio" alone asks the price table; "dólares/USD/VAN" on a curve or a campaign adds valorizar
        usd = any(w in q for w in ("dólar", "dolar", "usd", "u$s", " van", "valoriz", "plata"))
        valorizar = {"modo": "ultimo"}
        if "regal" in q:
            valorizar["regalia"] = 0.12
        if (
            "precio" in q
            and "precios" in nombres
            and not any(w in q for w in ("simul", "campaña", "campania", "curva", "pronóstic", "pronostic"))
        ):
            e = {"producto": "gas" if "gas" in q else "petroleo"}
            if cohortes:
                e["desde"] = f"{cohortes[0]}-01"
            plan.append(("precios", e))
        elif any(w in q for w in ("simul", "campaña de", "campania de")) and "simular_campania" in nombres:
            n = re.search(r"(\d{1,3})\s+pozos", q)
            e = {"formacion": formacion, "n_pozos": int(n.group(1)) if n else 10, "meses": 120, "n_sim": 300}
            if ventana:
                e["ventana"] = ventana
            if cohortes:
                e["cohorte_ref"] = cohortes[0]
            rama = re.search(r"(\d{3,4})\s*m\b", q)
            if rama:
                e["rama_m"] = float(rama.group(1))
            if usd:
                e["valorizar"] = valorizar
            plan.append(("simular_campania", e))
        elif (
            sigla
            and any(w in q for w in ("pronóstic", "pronostic", "eur", "declinaci"))
            and "pronosticar_pozo" in nombres
        ):
            plan.append(("buscar_pozo", {"texto": sigla.group(0)}))
        elif sigla:
            plan.append(("buscar_pozo", {"texto": sigla.group(0)}))
        elif any(w in q for w in ("fecha", "metadatos", "descarg", "versión", "version")):
            plan.append(("metadatos", {}))
        elif "curva" in q and "curva_tipo" in nombres:
            nivel = "cohorte_formacion_ventana" if ventana else "cohorte_formacion"
            claves = {"cohorte": cohortes[0] if cohortes else 2022, "formacion": formacion}
            if ventana:
                claves["ventana"] = ventana
            e = {"nivel": nivel, "claves": claves, "mes_max": 12}
            if usd:
                e["mes_max"] = 36
                e["valorizar"] = valorizar
            plan.append(("curva_tipo", e))
        elif any(w in q for w in ("ranking", "mejor", "peor", "ordena", "top")) and "ranking" in nombres:
            filtros: dict = {"formacion": formacion}
            if ventana:
                filtros["ventana"] = ventana
            if cohortes:
                filtros["cohorte"] = cohortes[0]
            plan.append(("ranking", {"filtros": filtros, "top": 5}))
        elif (
            any(w in q for w in ("compar", "operadora", "ventana", "cohorte", "rama", "etapa"))
            and "comparar_grupo" in nombres
        ):
            entrada: dict = {"formacion": formacion}
            if cohortes:
                entrada["cohorte"] = cohortes[0]
            if "ventana" in q:
                entrada["dimension"] = "ventana"
            elif "cohorte" in q and not cohortes:
                entrada["dimension"] = "cohorte"
            if "rama" in q:
                entrada["metrica"] = "rama_m"
            elif "etapa" in q:
                entrada["metrica"] = "etapas"
            plan.append(("comparar_grupo", entrada))
        elif "tabla" in q or "columna" in q:
            t = next((t for t in ("curvas_tipo", "indicadores", "pozos") if t in q), "indicadores")
            plan.append(("describir_tabla", {"tabla": t}))
        else:
            plan.append(("metadatos", {}))
        return plan

    @staticmethod
    def _resultados(messages: list[dict]) -> list[tuple[dict, dict]]:
        """``[(tool_use block, parsed result)...]`` for every tool call so far."""
        usos: dict[str, dict] = {}
        out = []
        for m in messages:
            if isinstance(m.get("content"), str):
                continue
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    usos[b["id"]] = b
                elif b.get("type") == "tool_result":
                    try:
                        parsed = json.loads(b["content"])
                    except (TypeError, ValueError):
                        parsed = {"error": b["content"]}
                    out.append((usos.get(b["tool_use_id"], {}), parsed))
        return out

    def crear(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        pregunta = next(
            m["content"] for m in messages if m["role"] == "user" and isinstance(m["content"], str)
        )
        resultados = self._resultados(messages)
        corregido = any(
            m["role"] == "user" and isinstance(m["content"], str) and m["content"].startswith("Validador:")
            for m in messages
        )
        if not resultados:
            content = [self._tool_use(n, e) for n, e in self._plan(pregunta, tools)]
            return {"content": content, "stop_reason": "tool_use", "usage": {}}
        # a search that found wells -> fetch the first one's sheet
        ultimo_uso, ultimo = resultados[-1]
        if ultimo_uso.get("name") == "buscar_pozo" and ultimo.get("datos", {}).get("pozos"):
            clave = ultimo["datos"]["pozos"][0]["sigla_clave"]
            q = pregunta.lower()
            if any(w in q for w in ("pronóstic", "pronostic", "eur", "declinaci")):
                return {
                    "content": [self._tool_use("pronosticar_pozo", {"sigla": clave, "n_bootstrap": 100})],
                    "stop_reason": "tool_use",
                    "usage": {},
                }
            return {
                "content": [self._tool_use("ficha_pozo", {"sigla_clave": clave})],
                "stop_reason": "tool_use",
                "usage": {},
            }
        texto = self._redactar(resultados, inventar=self.con_numero_inventado and not corregido)
        return {"content": [{"type": "text", "text": texto}], "stop_reason": "end_turn", "usage": {}}

    @staticmethod
    def _cita(r: dict) -> str:
        c = r.get("cita", {})
        filtros = ", ".join(f"{k} = {v}" for k, v in c.get("filtros", {}).items())
        return (
            f"[{c.get('tabla')}: {', '.join(c.get('columnas', [])[:4])}{'; ' + filtros if filtros else ''}]"
        )

    @staticmethod
    def _usd(usd: dict | None, etiquetas: tuple[str, ...], horizonte: str) -> list[str]:
        """The USD block of a result as lines, with its own citation (F6)."""
        if not usd:
            return []
        if usd.get("sin_dato_porque"):
            return [f"  USD: sin dato porque {usd['sin_dato_porque']}"]
        c = usd.get("cita", {})
        filtros = ", ".join(f"{k} = {v}" for k, v in c.get("filtros", {}).items())
        out = []
        for e in etiquetas:
            t = (usd.get(e) or {}).get("total")
            if not t:
                continue
            out.append(
                f"  · USD {e} ({horizonte}, precio {usd.get('modo')}): ingreso {t.get('ingreso_usd')} USD"
                f"{' (bruto ' + str(t.get('bruto_usd')) + ', regalía ' + str(t.get('regalia_usd')) + ')' if usd.get('regalia') else ' bruto'}, "
                f"VAN {t.get('van_usd')} USD al {usd.get('tasa_anual')} anual [{c.get('tabla')}: {', '.join(c.get('columnas', [])[:3])}; {filtros}]"
            )
        notas = usd.get("notas") or []
        if notas:
            out.append(f"  Nota USD: {notas[0]}")
        return out

    def _redactar(self, resultados: list[tuple[dict, dict]], inventar: bool) -> str:
        partes = [
            "(respuesta del proveedor mock: sin modelo, armada sólo con los resultados de las herramientas)"
        ]
        pie = None
        for uso, r in resultados:
            nombre = uso.get("name", "?")
            if "error" in r and "datos" not in r:
                partes.append(f"- {nombre}: error — {r['error']}")
                continue
            d = r.get("datos", {})
            cita = self._cita(r)
            if nombre == "ficha_pozo":
                i, m = d.get("indicadores", {}), d.get("maestro", {})
                partes.append(
                    f"- Pozo {m.get('sigla')} ({i.get('operadora') or m.get('operadora')}, {i.get('formacion')}, "
                    f"cohorte {i.get('cohorte')}, ventana {i.get('ventana')}): rama_m = {i.get('rama_m')}, etapas = "
                    f"{i.get('etapas')}, ip90_petroleo_m3_d = {i.get('ip90_petroleo_m3_d')} m³/d por día efectivo, "
                    f"ip90_petroleo_m3_d_por_m = {i.get('ip90_petroleo_m3_d_por_m')}, gor12_m3_m3 = {i.get('gor12_m3_m3')} {cita}"
                )
                sin = d.get("sin_dato_porque", {})
                if sin:
                    muestra = sorted(sin.items(), key=lambda kv: "flags" not in kv[1])[:4]
                    partes.append("  Sin dato porque: " + "; ".join(f"{k}: {v}" for k, v in muestra))
            elif nombre in ("ranking", "comparar_grupo"):
                filas = d.get("ranking") or d.get("grupos") or []
                partes.append(f"- {nombre} de {d.get('metrica')} ({d.get('unidad')}) {cita}:")
                for f in filas[:5]:
                    partes.append(
                        f"  · {f.get('grupo')}: mediana {f.get('mediana')}, P25 {f.get('p25')}, P75 {f.get('p75')}, "
                        f"n = {f.get('n_con_dato')} de {f.get('n_pozos')}"
                    )
                if d.get("sin_dato_porque"):
                    partes.append(
                        "  Sin dato porque: "
                        + "; ".join(f"{k}: {v}" for k, v in d["sin_dato_porque"].items())
                    )
            elif nombre == "curva_tipo":
                partes.append(f"- Curva tipo de {d.get('tasa')} por día efectivo {cita}:")
                for f in d.get("meses", [])[:6]:
                    partes.append(
                        f"  · mes {f.get('mes')}: P50 {f.get('p50')} (P10 {f.get('p10')}, P90 {f.get('p90')}), n = {f.get('n_pozos')}"
                        + (f" — {f['sin_dato_porque']}" if f.get("sin_dato_porque") else "")
                    )
                partes += self._usd(d.get("usd"), ("p50", "p10", "p90"), f"{d.get('n_meses')} meses")
            elif nombre == "precios":
                rs = d.get("resumen", {})
                partes.append(
                    f"- Precio de {d.get('producto')} en {d.get('region')} ({d.get('segmento')}"
                    f"{', ' + d['contrato'] if d.get('contrato') else ''}), {d.get('desde')} a {d.get('hasta')}: "
                    f"último {rs.get('ultimo')} {d.get('unidad_dataset')} ({d.get('ultimo_mes_publicado')}), promedio {rs.get('promedio')}, "
                    f"mín {rs.get('min')}, máx {rs.get('max')} {cita}"
                )
                for f in d.get("meses", [])[-3:]:
                    partes.append(
                        f"  · {f.get('mes')}: {f.get('precio_dataset')} {d.get('unidad_dataset')} = {f.get('precio_usd_mil_m3')} USD/mil m³"
                        + (" (provisorio)" if f.get("provisorio") else "")
                    )
                if d.get("sin_dato_porque"):
                    partes.append(f"  Sin dato porque: {d['sin_dato_porque']}")
            elif nombre == "buscar_pozo":
                partes.append(f"- buscar_pozo: {d.get('n')} coincidencia(s) {cita}")
            elif nombre == "describir_tabla":
                partes.append(
                    f"- {d.get('tabla')}: {d.get('filas')} filas, {d.get('n_columnas')} columnas; doc {d.get('doc')} {cita}"
                )
            elif nombre == "metadatos":
                tablas = ", ".join(f"{t} {v['filas']} filas" for t, v in d.get("tablas", {}).items())
                partes.append(f"- Datos: {tablas} {cita}")
            elif nombre == "cargar_mis_pozos":
                partes.append(
                    f"- Mis pozos cargados: {d.get('n_pozos')} pozos, {d.get('filas_pozo_mes')} filas pozo-mes, "
                    f"período {d.get('periodo')}, cohortes {d.get('pozos_por_cohorte')}"
                    + (" — DATOS SINTÉTICOS" if d.get("sintetico") else "")
                    + f" {cita}"
                )
            elif nombre == "comparar_mi_pozo":
                p, g, rs = d.get("pozo", {}), d.get("grupo", {}), d.get("resumen", {})
                partes.append(
                    f"- Mi pozo {p.get('sigla_original')} contra {g.get('nivel')} {g.get('cohorte')}/{g.get('formacion')}"
                    f"{'/' + g['ventana'] if g.get('ventana') else ''} ({d.get('tasa')}): percentil mediano P{rs.get('percentil_mediano')}, "
                    f"{rs.get('meses_sobre_p50')} de {rs.get('n_meses_comparados')} meses sobre P50, mío/P50 mediano {rs.get('ratio_p50_mediano')} {cita}"
                )
                for k, v in d.get("indicadores_vs_grupo", {}).items():
                    if "mio" in v:
                        partes.append(
                            f"  · {k}: mío {v['mio']} vs mediana pública {v['mediana_publica']} (n = {v['n_publico']}); "
                            f"supera al {v['supera_pct_publicos']} % de los pozos públicos"
                        )
                for f in d.get("meses", [])[:3]:
                    partes.append(
                        f"  · mes {f.get('mes')}: mío {f.get('mio')}, P50 {f.get('p50')}, percentil P{f.get('percentil')}"
                    )
                partes += self._usd(d.get("usd"), ("mio", "grupo_p50"), f"{rs.get('n_meses_mios')} meses")
            elif nombre == "comparar_mi_campania":
                rs = d.get("resumen", {})
                partes.append(
                    f"- Mi campaña ({d.get('metrica')}, filtros {d.get('filtros')}): {rs.get('n_comparados')} de {rs.get('n_mios')} "
                    f"pozos comparados; mediana mía {rs.get('mediana_mia')} vs mediana de medianas públicas "
                    f"{rs.get('mediana_de_medianas_publicas')}; {rs.get('pozos_sobre_mediana_publica')} pozos sobre la mediana pública; "
                    f"supera % mediano {rs.get('supera_pct_mediano')} {cita}"
                )
                for f in d.get("pozos", [])[:4]:
                    partes.append(
                        f"  · {f.get('sigla')} ({f.get('grupo') or f.get('sin_dato_porque')}): mío {f.get('mio')}, "
                        f"mediana pública {f.get('mediana_publica')}, supera {f.get('supera_pct_publicos')} %"
                    )
            elif nombre == "brechas":
                t = d.get("total", {})
                partes.append(
                    f"- Brechas contra P50 ({d.get('tasa')}, hasta el mes {d.get('mes_max')}): acumulado mío {t.get('acum_mio')} "
                    f"{d.get('unidad_volumen')} vs {t.get('acum_p50')} a P50, brecha {t.get('brecha_acum')} ({t.get('brecha_acum_pct')} %); "
                    f"{t.get('pozos_debajo_p50_acum')} de {d.get('n_pozos')} pozos por debajo {cita}"
                )
                for f in d.get("pozos", [])[:3]:
                    tr = f.get("tramos_debajo", {})
                    partes.append(
                        f"  · {f.get('sigla')}: {f.get('meses_debajo_p50')} de {f.get('meses_comparados')} meses debajo de P50 "
                        f"(0-5: {tr.get('meses_0_5')}, 6-11: {tr.get('meses_6_11')}, 12+: {tr.get('meses_12_mas')}), brecha acumulada "
                        f"{f.get('brecha_acum')} ({f.get('brecha_acum_pct')} %), peor mes {f.get('peor_mes', {}).get('mes')}"
                    )
            elif nombre == "pronosticar_pozo":
                b = d.get("banda_bootstrap", {})
                partes.append(
                    f"- Pronóstico de {d.get('pozo', {}).get('sigla')} ({d.get('tasa')}): modelo {d.get('modelo')} {d.get('parametros')}, "
                    f"{d.get('n_meses_ajustados')} meses ajustados, EUR a {d.get('horizonte_meses')} meses {d.get('eur')} {d.get('unidad_volumen')} "
                    f"(histórico {d.get('historia_acumulada')}, restante {d.get('eur_restante')}); banda bootstrap P90 {b.get('eur_p90')} / "
                    f"P50 {b.get('eur_p50')} / P10 {b.get('eur_p10')} ({b.get('n')} réplicas) {cita}"
                )
            elif nombre == "simular_campania":
                f = d.get("final", {})
                g = d.get("grupo", {})
                partes.append(
                    f"- Campaña simulada de {d.get('n_pozos')} pozos ({g.get('formacion')} {g.get('cohorte_ref')}"
                    f"{', ' + g['ventana'] if g.get('ventana') else ''}, {d.get('n_sim')} corridas): acumulado a {d.get('meses')} meses "
                    f"P90 {f.get('acumulado_p90')} / P50 {f.get('acumulado_p50')} / P10 {f.get('acumulado_p10')} {d.get('unidad_volumen')}; "
                    f"por pozo P50 {f.get('por_pozo_p50')}; tasa pico P50 {f.get('tasa_pico_p50')} en el mes {f.get('mes_pico_p50')} {cita}"
                )
                partes += self._usd(d.get("usd"), ("p50", "p10", "p90"), f"{d.get('meses')} meses")
            else:
                partes.append(f"- {nombre}: {json.dumps(d, ensure_ascii=False)[:400]} {cita}")
            for e in r.get("exclusiones", []):
                partes.append(f"  Exclusión: {e}")
            if r.get("notas"):
                partes.append(f"  Nota: {r['notas'][0]}")
            pie = f"Datos: descargados el {r.get('fecha_datos')}, maestro {r.get('version_maestro')}, fuente {r.get('fuente')}"
        if inventar:
            partes.append("- El promedio general sería de 123456,7 m³/d (estimación propia).")
        if pie:
            partes.append(pie)
        return "\n".join(partes)


# --- the loop ---------------------------------------------------------------------------------------------------


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def responder(
    pregunta: str,
    d: Datos,
    proveedor: Proveedor,
    con_sql: bool = False,
    historial: list[dict] | None = None,
    al_llamar: Callable[[Llamada], None] | None = None,
    max_turnos: int = MAX_TURNOS,
    reintentos_validador: int = 1,
) -> Respuesta:
    """Answer one question. ``historial`` (previous turns, API shape) is extended in place for chat mode."""
    tools = H.definiciones(con_sql)
    messages = historial if historial is not None else []
    messages.append({"role": "user", "content": pregunta})
    resp = Respuesta(pregunta=pregunta, texto="", proveedor=proveedor.nombre, modelo=proveedor.modelo)
    resultados: list[Any] = []
    permitidos: list[str] = [pregunta]
    uso_total: dict[str, int] = {}
    for _ in range(max_turnos):
        resp.turnos += 1
        msg = proveedor.crear(SYSTEM, messages, tools)
        for k, v in (msg.get("usage") or {}).items():
            if isinstance(v, int):
                uso_total[k] = uso_total.get(k, 0) + v
        messages.append({"role": "assistant", "content": msg["content"]})
        usos = [b for b in msg["content"] if b.get("type") == "tool_use"]
        if msg.get("stop_reason") == "refusal":
            resp.texto = "El modelo rechazó la consulta (stop_reason = refusal)."
            break
        if usos:
            bloques = []
            for u in usos:
                t0 = time.perf_counter()
                try:
                    salida = H.ejecutar(d, u["name"], u.get("input") or {}, con_sql=con_sql)
                    error = False
                except H.ErrorHerramienta as e:
                    salida, error = {"error": str(e)}, True
                llamada = Llamada(u["name"], u.get("input") or {}, salida, error, time.perf_counter() - t0)
                resp.llamadas.append(llamada)
                if al_llamar:
                    al_llamar(llamada)
                resultados.append(salida)
                permitidos.append(_json(u.get("input") or {}))
                bloques.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": u["id"],
                        "content": _json(salida),
                        "is_error": error,
                    }
                )
            messages.append({"role": "user", "content": bloques})
            continue
        texto = "\n".join(b.get("text", "") for b in msg["content"] if b.get("type") == "text").strip()
        val = validar(texto, resultados, permitidos)
        resp.validacion = val
        if not val.ok and resp.reintentos < reintentos_validador:
            resp.reintentos += 1
            messages.append({"role": "user", "content": "Validador: " + val.mensaje()})
            continue
        resp.texto = (
            texto
            if val.ok
            else f"ATENCION, número sin cita ({', '.join(val.sin_cita)}); respuesta no verificada:\n\n{texto}"
        )
        break
    else:
        resp.texto = f"Sin respuesta en {max_turnos} turnos."
    resp.uso = uso_total
    return resp


def elegir_proveedor(
    nombre: str = "auto", modelo: str = MODELO_DEFAULT, esfuerzo: str = ESFUERZO_DEFAULT
) -> Proveedor:
    """``auto``: Anthropic when ``ANTHROPIC_API_KEY`` is set, else the mock (and say so on stderr)."""
    if nombre == "auto":
        nombre = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "mock"
        if nombre == "mock":
            import sys

            print("ANTHROPIC_API_KEY no está definida: uso el proveedor mock (sin modelo).", file=sys.stderr)
    if nombre == "mock":
        return ProveedorMock()
    if nombre == "mock-sin-cita":
        return ProveedorMock(con_numero_inventado=True)
    if nombre == "anthropic":
        return ProveedorAnthropic(modelo=modelo, esfuerzo=esfuerzo)
    raise ValueError(f"proveedor desconocido: {nombre!r} (auto, anthropic, mock, mock-sin-cita)")
