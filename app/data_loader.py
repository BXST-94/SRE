#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_loader.py — Carga y unifica los datos precalculados para la app Flask.

Reglas:
- Solo lee archivos ya existentes. No llama a la API. No escribe nada.
- Si falta un archivo opcional, devuelve dict/list vacío y avisa por consola.
- El usuario de demo (AG3F...) tiene todo; otros usuarios solo tendrán perfil si
  se procesaron antes.
"""
import os as _os
_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # raiz de la carpeta presentacion
def _P(*partes):
    return _os.path.join(_RAIZ, *partes)

import json
import re
import math
from pathlib import Path

import pandas as pd

# ===================== Rutas =====================

CACHE = Path(_P("cache"))
USUARIOS_DIR = CACHE / "usuarios"
EN_VIVO_DIR = CACHE / "en_vivo"  # ejecuciones en vivo: cache/en_vivo/<uid>/<fecha>/
APP_DIR = Path(__file__).resolve().parent
UID_RE = re.compile(r"^[A-Z0-9]{10,40}$")
# Usuarios fijos de la demo en vivo: al prepararla no tenian carpeta en cache/usuarios ni filas en llm.sqlite
USUARIOS_FIJOS = [
    "AEBGPQYBCUI5ISFFEBIQU427VV3A",
    "AEGCKDJK2YKEYCGMSYI4EBTNDCVQ",
    "AGOXHMFS7YFZI2SJ7VENTF66MMZQ",
    "AHCWSSJ5JGMIGX5DPF2EZFTRZQTQ",
    "AFV3GWH2ALN24PLY6LZ43A2L6QLQ",
]
EXCLUIDOS_DEMO = set()  # uids del lote que se quitan de la demo (vacio = ninguno)
EVAL_USERS_CSV = Path(_P("data", "processed", "eval_users.csv"))
ATRIBUCION_JSON = CACHE / "atribucion.json"
AG3F_UID = "AG3FEXIZOCYEPKXZXSPH6YC72BIA"
V2_CALL1 = CACHE / "v2_call1"
V2_CALL2 = CACHE / "v2_call2"
IMAGENES_TOP5 = CACHE / "imagenes_top5.json"
PARQUET = Path(_P("data", "processed", "interactions_final.parquet"))
META_CSV = Path(_P("data", "csv", "meta_electronics.csv"))
TOP5_CANDIDATOS = [
    Path(_P("data", "processed", "top5.csv")),
    CACHE / "top5.csv",
    Path(_P("top5.csv")),
]
METRICAS_CANDIDATOS = [
    Path(_P("data", "processed", "eval_results.json")),
    Path(_P("data", "processed", "metricas_eval.json")),
    CACHE / "eval_results.json",
    CACHE / "metricas_eval.json",
]

FRASE_DEFENSA = (
    "Las razones vienen del modelo; el LLM solo las expresa en palabras."
)
LIMITACION = (
    "Este prototipo mide fidelidad al modelo, no causalidad real."
)

# Caso de fallo documentado (Call #1 v1, pre-aprobación).
# Texto fijado a partir del reporte de v1 en PROGRESS.md.
CASO_FALLO = {
    "titulo": "Caso donde la explicación falla (Call #1 v1, antes de la compuerta)",
    "descripcion": (
        "Esta fue la primera llamada real, ejecutada antes de la compuerta de "
        "aprobación. El LLM citó fragmentos que no respaldan la afirmación:"
    ),
    "errores": [
        {
            "aspecto": "Rendimiento para uso ligero",
            "citado": "P6",
            "problema": "P6 es 'Great Find' (cables de cinta); el contenido sobre rendimiento está en P4/P5.",
        },
        {
            "aspecto": "Durabilidad",
            "citado": "P2",
            "problema": "P2 es el router de viaje; no hay respaldo visible de 'durabilidad'.",
        },
        {
            "aspecto": "Advertencia (roturas/fallan pronto)",
            "citado": "P3",
            "problema": "P3 (1★) está bien citada, pero 'roturas/fallan pronto' no aparecen en el texto.",
        },
    ],
    "respaldadas": ["P1"],
    "leccion": (
        "Por esto se añadió la compuerta --aprobar y el verificador automático: "
        "una cita válida no basta si el fragmento no aparece literal en la reseña."
    ),
}


# ===================== Utilidades =====================

def _leer_json(path: Path, default=None):
    if not path.exists():
        print(f"[data_loader] falta: {path}")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[data_loader] error leyendo {path}: {e}")
        return default


def _corridas(uid: str) -> list:
    """Ejecuciones en vivo COMPLETAS (con meta.json) de un usuario, de la mas antigua a la mas reciente."""
    base = EN_VIVO_DIR / uid
    if not UID_RE.match(uid) or not base.is_dir():
        return []
    return sorted(d for d in base.iterdir() if d.is_dir() and (d / "meta.json").exists())


def _ultima_corrida(uid: str):
    """Carpeta de la ultima ejecucion en vivo completa del usuario, o None si no hay ninguna."""
    c = _corridas(uid)
    return c[-1] if c else None


def _paths_usuario(uid: str):
    """Rutas de la ultima ejecucion en vivo del usuario, o None. No se lee nada de cache/usuarios ni del layout legacy."""
    run = _ultima_corrida(uid)
    if run is None:
        return None
    return {
        "perfil":        run / "call1" / "perfil_v2.json",
        "explicaciones": run / "call2" / "explicaciones_v2.json",
        "verif_call1":   run / "verif_call1.json",
        "verif_call2":   run / "verif_call2.json",
        "meta":          run / "meta.json",
    }


def _leer_de_usuario(uid: str, clave: str, vacio):
    """Lee un archivo del usuario; devuelve 'vacio' si no hay cache o falta el archivo."""
    p = _paths_usuario(uid)
    if not p:
        return vacio
    return _leer_json(p[clave]) or vacio


def _leer_csv(path: Path, **kwargs):
    if not path.exists():
        print(f"[data_loader] falta: {path}")
        return None
    try:
        return pd.read_csv(path, **kwargs)
    except Exception as e:
        print(f"[data_loader] error leyendo {path}: {e}")
        return None


def _encontrar_primero(candidatos):
    for p in candidatos:
        if p.exists():
            return p
    return None


# ===================== Cargas individuales =====================



def _limpiar_html(t):
    """Limpia <br />, etiquetas HTML y colapsa espacios."""
    if not t:
        return ""
    t = re.sub(r"<br\s*/?>", " ", str(t))
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()

def _precio_sanitizado(p):
    """Devuelve precio legible o None si es NaN/None/string vacío."""
    if p is None:
        return None
    try:
        f = float(p)
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


_ETIQUETAS_FLAG = {
    "CITA_R3_RATING_1.0": "Cita una reseña negativa como preferencia",
    "CITA_R3_RATING_2.0": "Cita una reseña de 2★ como preferencia",
    "CITA_R3_RATING_3.0": "Cita una reseña de 3★ como preferencia",
    "REUSO_R3_EN_CC_Y_TEC": "La misma reseña se cita en «coincide» y en «ten en cuenta»",
    "FRAG_NO_LITERAL": "Fragmento no literal en la fuente",
}


def _etiqueta_flag(flag):
    """Traduce un código interno a etiqueta legible."""
    if flag in _ETIQUETAS_FLAG:
        return _ETIQUETAS_FLAG[flag]
    # Fallback: genérico
    return flag.replace("_", " ").lower().capitalize()

def cargar_perfil(uid: str) -> dict:
    """Perfil v2 (Call #1) del usuario."""
    return _leer_de_usuario(uid, "perfil", {"preferencias": [], "advertencias": []})


def cargar_verif_call1(uid: str) -> dict:
    """Verificación de Call #1 del usuario."""
    return _leer_de_usuario(uid, "verif_call1", {"elementos": [], "veredicto_global": "?"})


def cargar_explicaciones(uid: str) -> dict:
    """Explicaciones v2 (Call #2) del usuario."""
    return _leer_de_usuario(uid, "explicaciones", {"items": []})


def cargar_verif_call2(uid: str) -> dict:
    """Verificación de Call #2 del usuario."""
    return _leer_de_usuario(uid, "verif_call2", {"items": [], "resumen": {}})


def cargar_atribucion(uid: str) -> list:
    data = _leer_json(CACHE / "atribucion.json") or {}
    return data.get("usuarios", {}).get(uid, [])


def cargar_mapa(uid: str) -> dict:
    """Mapa alias (P#) -> datos de la evidencia, de la ultima ejecucion en vivo del usuario."""
    run = _ultima_corrida(uid)
    if run is None:
        return {}
    return (_leer_json(run / "mapa_alias.json") or {}).get(uid, {})


def cargar_imagenes() -> dict:
    """Carga {parent_asin: url} desde cache/imagenes_top5.json."""
    return _leer_json(IMAGENES_TOP5) or {}

def cargar_meta() -> dict:
    """Carga metadatos desde el índice cacheado (meta_index.parquet)."""
    try:
        import meta_index
        return meta_index.load_meta()
    except Exception:
        # Fallback a lectura directa si falla el índice
        df = _leer_csv(META_CSV, usecols=["parent_asin", "title", "main_category", "price"],
                       low_memory=False)
        if df is None:
            return {}
        return df.set_index("parent_asin")[["title", "main_category", "price"]].to_dict("index")


def cargar_historial(uid: str, n: int = 5, imagenes: dict = None) -> list:
    """Últimas n interacciones del usuario desde el parquet (todas las particiones)."""
    if not PARQUET.exists():
        return []
    df = pd.read_parquet(
        PARQUET,
        columns=["user_id", "parent_asin", "item_title", "rating",
                 "timestamp", "split", "helpful_vote"],
        filters=[("user_id", "==", uid)],
    )
    if len(df) == 0:
        return []
    if imagenes is None:
        imagenes = cargar_imagenes()
    df = df.sort_values("timestamp", ascending=False).head(n)
    return [
        {
            "parent_asin": row.parent_asin,
            "titulo": str(row.item_title)[:120] if pd.notna(row.item_title) else "",
            "rating": float(row.rating),
            "timestamp": int(row.timestamp),
            "split": str(row.split),
            "helpful_vote": int(row.helpful_vote),
            "imagen": imagenes.get(row.parent_asin),
        }
        for row in df.itertuples()
    ]


def cargar_top5(uid: str) -> list:
    """Top-5 del usuario (CSV). Si falta, deriva del atribucion.json."""
    path = _encontrar_primero(TOP5_CANDIDATOS)
    if path:
        df = _leer_csv(path)
        if df is not None and "user_id" in df.columns:
            df_u = df[df["user_id"].astype(str) == uid]
            if len(df_u) > 0:
                return df_u.sort_values("rank").to_dict("records")
    # Fallback: derivar de atribucion.json
    atrib = cargar_atribucion(uid)
    return [
        {"user_id": uid, "rank": it["rank"], "parent_asin": it["parent_asin"],
         "score": it.get("logit")}
        for it in atrib
    ]


def cargar_metricas() -> dict:
    """Métricas HR@5/NDCG@5. Devuelve dict vacío si no las encuentra."""
    path = _encontrar_primero(METRICAS_CANDIDATOS)
    if not path:
        print("[data_loader] no se encontraron métricas HR@5/NDCG@5")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[data_loader] error leyendo métricas: {e}")
        return {}


# ===================== Ensamblado =====================

def _insignia_item(item_verif: dict) -> tuple:
    """
    Devuelve (texto, clase_css).
    - OK: todos los flags vacíos.
    - Con nota: flags no críticos (CITA_*, REUSO_*, ASPECT_*).
    - Fallo: FRAG_NO_LITERAL, ID_*_NO_EXISTE, PALABRAS>15.
    """
    todos_flags = []
    for cc in item_verif.get("coincide_con", []):
        todos_flags.extend(cc.get("flags", []))
    tec = item_verif.get("ten_en_cuenta")
    if tec:
        todos_flags.extend(tec.get("flags", []))

    criticos = {"FRAG_NO_LITERAL", "ID_", "PALABRAS="}
    es_critico = any(
        any(f.startswith(c) for c in criticos) for f in todos_flags
    )
    if es_critico:
        return ("Fallo", "badge-fallo")
    if todos_flags:
        return ("Con nota", "badge-nota")
    return ("Verificado", "badge-ok")


def _producto_de(pa, meta, imagenes) -> dict:
    """Producto de una resena de atribucion: asin, nombre (meta_index, o el asin si falta) e imagen (o None)."""
    m = meta.get(pa, {}) if pa else {}
    t = m.get("title") if isinstance(m, dict) else None
    t = _limpiar_html(t) if isinstance(t, str) and t.strip() else ""
    return {
        "producto_asin": pa or "",
        "producto_titulo": (t or str(pa or "?"))[:120],
        "producto_imagen": imagenes.get(pa) if pa else None,
    }


def cargar_todo(uid: str) -> dict:
    """Ensambla el dict completo para el template."""
    perfil = cargar_perfil(uid)
    verif1 = cargar_verif_call1(uid)
    explic = cargar_explicaciones(uid)
    verif2 = cargar_verif_call2(uid)
    atrib = cargar_atribucion(uid)
    mapa = cargar_mapa(uid)
    meta = cargar_meta()
    historial = cargar_historial(uid, n=5)
    top5 = cargar_top5(uid)
    metricas = cargar_metricas()
    imagenes = cargar_imagenes()

    # Diccionarios por parent_asin
    atrib_por_pa = {it["parent_asin"]: it for it in atrib}
    verif2_por_pos = {it["posicion"]: it for it in verif2.get("items", [])}

    # Mapa parent_asin -> alias (P1, P2, ...) construido UNA vez, gana el primero
    pa_a_alias = {}
    for alias, info in mapa.items():
        pa = info.get("parent_asin")
        if pa and pa not in pa_a_alias:
            pa_a_alias[pa] = alias

    items_render = []
    for it in explic.get("items", []):
        pos = it["posicion"]
        pa = it["parent_asin"]
        m = meta.get(pa, {})
        razones_raw = atrib_por_pa.get(pa, {}).get("razones", [])
        razones = [
            {
                "id": pa_a_alias.get(r.get("removed_parent_asin"), "?"),
                "peso": float(r.get("weight") or 0),
                "delta_logit": float(r.get("delta_logit") or 0),
                "removed_title": _limpiar_html(r.get("title") or ""),
                "removed_rating": r.get("rating"),
                "removed_text": _limpiar_html(r.get("text") or ""),
                "split": str(r.get("split") or ""),
                **_producto_de(r.get("removed_parent_asin"), meta, imagenes),
            }
            for r in razones_raw
        ]
        v = verif2_por_pos.get(pos, {})
        badge_txt, badge_cls = _insignia_item(v)

        coincide = []
        for cc in it.get("coincide_con", []):
            cc_verif = next(
                (x for x in v.get("coincide_con", [])
                 if x.get("rid") == cc.get("id") and x.get("aspecto") == cc.get("aspecto")),
                {},
            )
            coincide.append({
                "aspecto": cc.get("aspecto", ""),
                "fragmento": cc.get("fragmento", ""),
                "id": cc.get("id", ""),
                "flags": [_etiqueta_flag(f) for f in cc_verif.get("flags", [])],
            })

        tec = None
        if it.get("ten_en_cuenta"):
            t = it["ten_en_cuenta"]
            tec_v = v.get("ten_en_cuenta") or {}
            tec = {
                "texto": t.get("texto", ""),
                "fragmento": t.get("fragmento", ""),
                "id": t.get("id", ""),
                "flags": [_etiqueta_flag(f) for f in tec_v.get("flags", [])],
            }

        items_render.append({
            "posicion": pos,
            "parent_asin": pa,
            "titulo": str(m.get("title", pa))[:120],
            "categoria": m.get("main_category", ""),
            "precio": _precio_sanitizado(m.get("price")),
            "imagen": imagenes.get(pa),
            "por_que_el_modelo": it.get("por_que_el_modelo", ""),
            "coincide_con": coincide,
            "ten_en_cuenta": tec,
            "razones_atribucion": razones,
            "badge": {"texto": badge_txt, "clase": badge_cls},
        })

    return {
        "user_id": uid,
        "perfil": perfil,
        "verif_call1": verif1,
        "items": items_render,
        "historial": historial,
        "top5_raw": top5,
        "metricas": metricas,
        "caso_fallo": CASO_FALLO,
        "frase_defensa": FRASE_DEFENSA,
        "limitacion": LIMITACION,
        "mapa_alias": mapa,
    }


def _lote_probado() -> list:
    """Usuarios del lote probados (estrella): lista fija en data/demo_usuarios.json de esta carpeta (no se lee ningun resultado guardado)."""
    d = _leer_json(APP_DIR.parent / "data" / "demo_usuarios.json") or {}
    return [u for u in d.get("probados", []) if UID_RE.match(u)]


def usuarios_demo() -> list:
    """Usuarios que acepta la demo en vivo: los fijos y los del lote probados (fijos primero, sin duplicados)."""
    vistos = set()
    res = []
    for u in USUARIOS_FIJOS + _lote_probado():
        if u in EXCLUIDOS_DEMO or u in vistos:
            continue
        vistos.add(u)
        res.append(u)
    return res


def listar_usuarios_disponibles() -> list:
    """Para la pestana Cargar: fijos y lote probado. estrella = el lote lo completo antes; el clic igual llama al modelo real."""
    try:
        en_atrib = set(json.loads(ATRIBUCION_JSON.read_text(encoding="utf-8")).get("usuarios", {}).keys())
    except Exception:
        en_atrib = set()
    probados = set(_lote_probado())
    return [
        {"uid": u, "ejecutado": _ultima_corrida(u) is not None, "en_atribucion": u in en_atrib,
         "estrella": u in probados, "fijo": u in USUARIOS_FIJOS}
        for u in usuarios_demo()
    ]


def listar_usuarios_historial(extra_uid=None) -> list:
    """Usuarios de la demo con ejecucion en vivo completa y, si se pide, el solicitado (para mostrar sin ejecucion)."""
    demo = usuarios_demo()
    uids = [u for u in demo if _ultima_corrida(u) is not None]
    if extra_uid and extra_uid in demo and extra_uid not in uids:
        uids.append(extra_uid)
    return uids


def listar_usuarios_con_cache() -> list:
    """Compatibilidad: usuarios con ejecucion en vivo completa."""
    return listar_usuarios_historial()


# ===================== main (diagnóstico) =====================

if __name__ == "__main__":
    usuarios = listar_usuarios_con_cache()
    print(f"Usuarios con cache: {usuarios}")
    for uid in usuarios:
        print(f"\n=== {uid} ===")
        d = cargar_todo(uid)
        print(f"  Preferencias: {len(d['perfil'].get('preferencias', []))}")
        print(f"  Advertencias: {len(d['perfil'].get('advertencias', []))}")
        print(f"  Items Top-5: {len(d['items'])}")
        print(f"  Historial: {len(d['historial'])} entradas")
        print(f"  Métricas: {'OK' if d['metricas'] else 'vacío'}")
        print(f"  Veredicto Call #1: {d['verif_call1'].get('veredicto_global', '?')}")
        for it in d["items"]:
            cc = len(it["coincide_con"])
            tec = "sí" if it["ten_en_cuenta"] else "no"
            print(f"    #{it['posicion']} {it['parent_asin']} "
                  f"badge={it['badge']['texto']} cc={cc} tec={tec} "
                  f"titulo={it['titulo'][:50]}")