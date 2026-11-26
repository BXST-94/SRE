# -*- coding: utf-8 -*-
"""Orquesta un turno de chat: extraccion + busqueda + respuesta + verificacion.

Multi-turno respaldado por SQLite (`conversations.py`). El historial se lee
de la BD por conv_id, no lo envia el navegador.

Call #2 devuelve un objeto con resumen + tabla de productos + historial citado.
El texto plano "respuesta" ya no se usa (se mantiene por compatibilidad con
turnos antiguos guardados en BD).
"""
import json
import math as _math
import os
import re
from pathlib import Path

import conversations
import llm_client
import search as search_mod
from prompts_chat import (SYSTEM_EXTRACCION, SYSTEM_RESPUESTA,
                          user_extraccion, user_respuesta)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

PROFILES = DATA_DIR / "user_profiles.json"
DEMO = DATA_DIR / "demo_usuarios.json"

MODELO = "deepseek/deepseek-v4.1-flash-1017"
MAX_TOKENS = 12000
TEMPERATURE = 0.0
REASONING = "low"

_PROFILES_CACHE = None
_DEMO_CACHE = None


def _limpio(v):
    if v is None:
        return None
    if isinstance(v, float) and (_math.isnan(v) or _math.isinf(v)):
        return None
    try:
        import pandas as _pd
        if _pd.isna(v):
            return None
    except Exception:
        pass
    return v


def _sanitizar(obj):
    if isinstance(obj, dict):
        return {k: _sanitizar(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitizar(x) for x in obj]
    return _limpio(obj)


def _cargar_demo():
    global _DEMO_CACHE
    if _DEMO_CACHE is None:
        _DEMO_CACHE = json.loads(DEMO.read_text(encoding="utf-8"))
    return _DEMO_CACHE


def usuarios_demo():
    return list(_cargar_demo().get("uids", []))


def _cargar_profiles():
    global _PROFILES_CACHE
    if _PROFILES_CACHE is None:
        if PROFILES.exists():
            _PROFILES_CACHE = json.loads(PROFILES.read_text(encoding="utf-8"))
        else:
            _PROFILES_CACHE = {}
    return _PROFILES_CACHE


def cargar_perfil(uid):
    if not uid:
        return None
    return _cargar_profiles().get(uid)


def _parsear_json(texto):
    if not texto:
        return None
    try:
        return json.loads(texto)
    except Exception:
        m = re.search(r"\{.*\}", texto, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _resolver_api_key(api_key_de_visitante):
    k = (api_key_de_visitante or "").strip()
    if k:
        return k
    return (os.environ.get("DEMO_KEY") or "").strip()


PAT_ASIN = re.compile(r"\[?(B0[A-Z0-9]{8})\]?")
PAT_P = re.compile(r"\[(P\d+)\]")


def _formatear_historial(historial, max_turnos=3, max_chars=500):
    """historial: lista de dicts {rol, texto}"""
    if not historial:
        return ""
    lineas = []
    for turno in historial[-max_turnos * 2:]:
        rol = "USUARIO" if turno.get("rol") == "user" else "ASISTENTE"
        texto = (turno.get("texto") or "").strip()
        if not texto:
            continue
        lineas.append("[%s] %s" % (rol, texto[:max_chars]))
    return "\n".join(lineas)


def _enriquecer_producto(p, candidatos):
    """Completa el producto con title/imagen/rating del catalogo (si estan)."""
    asin = p.get("parent_asin")
    base = None
    for c in candidatos:
        if c.get("parent_asin") == asin:
            base = c
            break
    if base:
        return {
            "parent_asin": asin,
            "title": base.get("title"),
            "imagen": base.get("imagen"),
            "average_rating": base.get("average_rating"),
            "precio": p.get("precio", base.get("price")),
            "caracteristicas": p.get("caracteristicas", ""),
            "motivo": p.get("motivo", ""),
        }
    return {
        "parent_asin": asin,
        "title": p.get("title") or "(desconocido)",
        "imagen": None,
        "average_rating": None,
        "precio": p.get("precio"),
        "caracteristicas": p.get("caracteristicas", ""),
        "motivo": p.get("motivo", ""),
    }


def _enriquecer_historial(item, perfil):
    """Completa el P# con datos del perfil y la imagen del catalogo."""
    if not perfil:
        return item
    hist = perfil.get("historial_resumen", [])
    p_tag = item.get("p")
    try:
        idx = int(p_tag[1:]) - 1
    except (ValueError, TypeError, AttributeError):
        return item
    if not (0 <= idx < len(hist)):
        return item
    h = hist[idx]
    try:
        imgs = search_mod._cargar_imagenes()
    except Exception:
        imgs = {}
    return {
        "p": p_tag,
        "parent_asin": h.get("parent_asin"),
        "titulo": h.get("titulo"),
        "precio": h.get("precio"),
        "categoria": h.get("categoria"),
        "rating": h.get("rating"),
        "imagen": imgs.get(h.get("parent_asin")),
        "resumen": item.get("resumen", ""),
    }


def _verificar(texto_plano, productos, historial, candidatos, perfil):
    advertencias = []
    asins_validos = {c.get("parent_asin") for c in candidatos}
    for p in productos:
        a = p.get("parent_asin")
        if a and a not in asins_validos:
            advertencias.append("Se cito %s en la tabla y no esta en candidatos (se descarta)." % a)
    ps_validos = set()
    if perfil:
        for i, _ in enumerate(perfil.get("historial_resumen", []), 1):
            ps_validos.add("P%d" % i)
    for h in historial:
        p = h.get("p")
        if p and p not in ps_validos:
            advertencias.append("Se cito %s en historial y no existe en el perfil." % p)
    for m in PAT_ASIN.finditer(texto_plano or ""):
        a = m.group(1)
        if a not in asins_validos:
            advertencias.append("El texto cito %s y no esta en candidatos." % a)
    return advertencias


def _filtrar_productos(productos, candidatos):
    asins = {c.get("parent_asin") for c in candidatos}
    return [p for p in productos if p.get("parent_asin") in asins]


def _filtrar_historial(historial, perfil):
    if not perfil:
        return []
    validos = {"P%d" % i for i, _ in enumerate(perfil.get("historial_resumen", []), 1)}
    return [h for h in historial if h.get("p") in validos]


def procesar_turno(uid, mensaje, api_key_de_visitante=None, conv_id=None):
    mensaje = (mensaje or "").strip()
    if not mensaje:
        return {"ok": False, "error": "mensaje vacio"}

    api_key = _resolver_api_key(api_key_de_visitante)
    if not api_key:
        return {"ok": False, "error": "Falta la clave de OpenRouter (api_key)."}

    uid = (uid or "").strip() or "invitado"

    # 1. resolver/crear conversacion
    if not conv_id:
        conv_id = conversations.crear_conversacion(uid, mensaje)
    else:
        if not conversations.obtener_conversacion(conv_id):
            return {"ok": False, "error": "conv_id no existe."}

    # 2. cargar historial previo
    conv = conversations.obtener_conversacion(conv_id)
    historial_turnos = [{"rol": t["rol"], "texto": t["texto"]} for t in conv["turnos"]]

    # 3. guardar turno del usuario
    conversations.guardar_turno(conv_id, "user", mensaje)

    perfil = cargar_perfil(uid)

    perfil_titulos = ""
    perfil_categorias = ""
    if perfil:
        perfil_titulos = "; ".join(
            h.get("titulo", "")[:40] for h in perfil.get("historial_resumen", [])[:5]
        )
        perfil_categorias = ", ".join(perfil.get("top_categorias", [])[:3])

    hist_extraccion = _formatear_historial(historial_turnos, max_turnos=2, max_chars=300)
    hist_respuesta = _formatear_historial(historial_turnos, max_turnos=3, max_chars=500)

    # -------- Call 1: extraccion
    try:
        r1 = llm_client._call_openrouter(
            SYSTEM_EXTRACCION,
            user_extraccion(mensaje, perfil_titulos, perfil_categorias, hist_extraccion),
            MODELO, MAX_TOKENS, TEMPERATURE, REASONING,
            user_id=uid, call_name="chat_call1", api_key=api_key,
        )
    except Exception as e:
        msg = "Call #1 fallo: %s" % e
        conversations.guardar_turno(conv_id, "bot", "⚠️ " + msg, {"error": msg})
        return {"ok": False, "error": msg, "conv_id": conv_id}

    if not r1.content:
        msg = "Call #1 no devolvio contenido (finish_reason=%s)." % r1.finish_reason
        conversations.guardar_turno(conv_id, "bot", "⚠️ " + msg, {"error": msg})
        return {"ok": False, "error": msg, "conv_id": conv_id}

    consulta = _parsear_json(r1.content)
    if not isinstance(consulta, dict):
        msg = "Call #1 devolvio JSON invalido."
        conversations.guardar_turno(conv_id, "bot", "⚠️ " + msg, {"error": msg})
        return {"ok": False, "error": msg, "conv_id": conv_id}

    # -------- Busqueda local
    candidatos = search_mod.buscar(consulta, tope=20)

    if not candidatos:
        msg = "No tenemos esos productos en el catalogo."
        payload = {"resumen": msg, "productos": [], "historial": []}
        conversations.guardar_turno(conv_id, "bot", msg, payload)
        return _sanitizar({
            "ok": True, "conv_id": conv_id, "respuesta": msg,
            "consulta": consulta, "candidatos": [],
            "productos": [], "historial": [],
            "advertencias": [], "llamadas": 1,
        })

    # -------- Call 2: redaccion
    try:
        r2 = llm_client._call_openrouter(
            SYSTEM_RESPUESTA,
            user_respuesta(perfil, consulta, candidatos, hist_respuesta),
            MODELO, MAX_TOKENS, TEMPERATURE, REASONING,
            user_id=uid, call_name="chat_call2", api_key=api_key,
        )
    except Exception as e:
        msg = "Call #2 fallo: %s" % e
        conversations.guardar_turno(conv_id, "bot", "⚠️ " + msg, {"error": msg})
        return {"ok": False, "error": msg, "conv_id": conv_id}

    if not r2.content:
        msg = "Call #2 no devolvio contenido (finish_reason=%s)." % r2.finish_reason
        conversations.guardar_turno(conv_id, "bot", "⚠️ " + msg, {"error": msg})
        return {"ok": False, "error": msg, "conv_id": conv_id}

    final = _parsear_json(r2.content)
    if not isinstance(final, dict):
        msg = "Call #2 devolvio JSON invalido."
        conversations.guardar_turno(conv_id, "bot", "⚠️ " + msg, {"error": msg})
        return {"ok": False, "error": msg, "conv_id": conv_id}

    resumen = (final.get("resumen") or "").strip()
    productos_raw = final.get("productos") or []
    historial_raw = final.get("historial") or []

    if not isinstance(productos_raw, list):
        productos_raw = []
    if not isinstance(historial_raw, list):
        historial_raw = []

    advertencias = _verificar(
        final.get("respuesta", "") or resumen,
        productos_raw, historial_raw, candidatos, perfil)

    productos_filtrados = _filtrar_productos(productos_raw, candidatos)
    historial_filtrado = _filtrar_historial(historial_raw, perfil)

    productos_finales = [_enriquecer_producto(p, candidatos) for p in productos_filtrados]
    historial_final = [_enriquecer_historial(h, perfil) for h in historial_filtrado]

    if not resumen:
        if productos_finales:
            resumen = "Estas son las opciones que mejor encajan con lo que buscas."
        else:
            resumen = "No tenemos esos productos en el catalogo."

    payload = {
        "resumen": resumen,
        "productos": productos_finales,
        "historial": historial_final,
        "advertencias": advertencias,
    }
    conversations.guardar_turno(conv_id, "bot", resumen, payload)

    return _sanitizar({
        "ok": True,
        "conv_id": conv_id,
        "respuesta": resumen,  # compatibilidad con turnos viejos
        "consulta": consulta,
        "candidatos": [{"parent_asin": c.get("parent_asin"),
                        "title": c.get("title"),
                        "price": c.get("price"),
                        "average_rating": c.get("average_rating"),
                        "imagen": c.get("imagen")} for c in candidatos],
        "productos": productos_finales,
        "historial": historial_final,
        "advertencias": advertencias,
        "llamadas": 2,
    })