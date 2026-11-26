#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_pipeline.py — Orquesta Call #1 + Call #2 + verificación para UN usuario.

Resultado en cache/en_vivo/<uid>/<fecha>/:
    call1/prompt_call1_{system,user}.txt
    call1/perfil_v2.json
    call1/response_raw.json
    call1/verif_v2.json
    call2/prompt_call2_{system,user}.txt
    call2/explicaciones_v2.json
    call2/response_raw.json
    call2/verif_v2.json
    mapa.json            # {uid: {P1: {rating}, ...}} (aux para el verificador)
    verif_call1.json     # copia plana (lo que lee data_loader)
    verif_call2.json
    meta.json
"""
import os as _os
_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # raiz de la carpeta presentacion
def _P(*partes):
    return _os.path.join(_RAIZ, *partes)

import datetime
import json
import os
import threading
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, _P())
sys.path.append(_P("src"))  # perfil, prompts, llm_client, verifier

from api_key_manager import get_api_key, incrementar, puede_llamar
from jobs import Job

# Modelo principal
MODELO = "deepseek/deepseek-v4.1-flash-1017"
MAX_TOKENS_CALL1 = 12000
MAX_TOKENS_CALL2 = 12000
TEMPERATURE = 0.0
REASONING = "low"
LLAMADAS_POR_USUARIO = 2  # 1 Call #1 + 1 Call #2 (5 items en un solo prompt)

# Rutas
CACHE = Path(_P("cache"))
USUARIOS_DIR = CACHE / "usuarios"
EN_VIVO_DIR = CACHE / "en_vivo"
PARQUET = Path(_P("data", "processed", "interactions_final.parquet"))
META_CSV = Path(_P("data", "csv", "meta_electronics.csv"))
ATRIBUCION_JSON = CACHE / "atribucion.json"
USER_CUTOFF = Path(_P("data", "processed", "user_cutoff.csv"))

# Lock para evitar que dos jobs se pisen al monkey-patchear verifier
_PIPELINE_LOCK = threading.Lock()

# Cachés module-level (lazy)
_META_IDX = None
_CUTOFFS = None
_ATRIBUCION = None


# ============================================================
# Helpers de carga
# ============================================================

def _load_meta() -> dict:
    global _META_IDX
    if _META_IDX is None:
        df = pd.read_csv(META_CSV, usecols=["parent_asin", "title", "main_category", "price"],
                         dtype={"price": str}, low_memory=False)
        _META_IDX = df.set_index("parent_asin")[["title", "main_category", "price"]].to_dict("index")
    return _META_IDX


def _load_atribucion() -> dict:
    global _ATRIBUCION
    if _ATRIBUCION is None:
        _ATRIBUCION = json.loads(ATRIBUCION_JSON.read_text(encoding="utf-8"))
    return _ATRIBUCION


def _load_cutoffs() -> dict:
    global _CUTOFFS
    if _CUTOFFS is None:
        df = pd.read_csv(USER_CUTOFF)
        _CUTOFFS = dict(zip(df["user_id"].astype(str), df["cutoff_timestamp"].astype("int64")))
    return _CUTOFFS


def _get_cutoff(uid: str, df_user: pd.DataFrame) -> int:
    """Timestamp del test del usuario (precomputado o extraído del parquet)."""
    c = _load_cutoffs().get(uid)
    if c is not None:
        return int(c)
    test = df_user[df_user["split"] == "test"]
    if len(test):
        return int(test["timestamp"].iloc[0])
    return int(df_user["timestamp"].max())


def _load_user(uid: str) -> pd.DataFrame:
    return pd.read_parquet(
        PARQUET,
        columns=["user_id", "parent_asin", "item_title", "rating", "text",
                 "title", "timestamp", "split", "helpful_vote", "verified_purchase"],
        filters=[("user_id", "==", uid)],
    )


def _cargar_reviews_productos(parent_asins, cutoff: int) -> dict:
    """Reseñas de los 5 productos con timestamp < cutoff (anti-leakage)."""
    df = pd.read_parquet(
        PARQUET,
        columns=["parent_asin", "rating", "helpful_vote", "timestamp", "title", "text"],
        filters=[("parent_asin", "in", list(parent_asins))],
    )
    df = df[df["timestamp"] < cutoff]
    out = {}
    for pa in parent_asins:
        sub = df[df["parent_asin"] == pa]
        out[pa] = sub[["rating", "helpful_vote", "timestamp", "title", "text"]].to_dict("records")
    return out


def _grupo_historial_usuario(uid: str) -> pd.DataFrame:
    """Historial train+valid de UN usuario, con el mismo recorte que perfil.cargar_historial()."""
    df = pd.read_parquet(
        PARQUET,
        columns=["user_id", "review_id", "parent_asin", "asin", "rating", "title", "text",
                 "timestamp", "split", "helpful_vote", "verified_purchase",
                 "item_main_category", "item_title", "seq_idx"],
        filters=[("user_id", "==", uid)],
    )
    return df[df.split != "test"].sort_values(["timestamp", "seq_idx"], kind="mergesort")


# ============================================================
# Verificación con monkey-patch controlado
# ============================================================

def _verificar_call1(uid: str, cache_dir: Path, mapa: dict):
    import verifier as V
    old = (V.V2_CALL1, V.UID, V.MAPA_PATH)
    try:
        V.V2_CALL1 = cache_dir / "call1"
        V.UID = uid
        mapa_path = cache_dir / "mapa.json"
        mapa_path.write_text(json.dumps(mapa, ensure_ascii=False), encoding="utf-8")
        V.MAPA_PATH = mapa_path
        return V.verificar_call1()
    finally:
        V.V2_CALL1, V.UID, V.MAPA_PATH = old


def _verificar_call2(uid: str, cache_dir: Path, mapa: dict):
    import verifier as V
    old = (V.V2_CALL1, V.V2_CALL2, V.UID, V.MAPA_PATH)
    try:
        V.V2_CALL1 = cache_dir / "call1"
        V.V2_CALL2 = cache_dir / "call2"
        V.UID = uid
        mapa_path = cache_dir / "mapa.json"
        mapa_path.write_text(json.dumps(mapa, ensure_ascii=False), encoding="utf-8")
        V.MAPA_PATH = mapa_path
        return V.verificar_call2()
    finally:
        V.V2_CALL1, V.V2_CALL2, V.UID, V.MAPA_PATH = old


# ============================================================
# Pipeline principal
# ============================================================

def ejecutar_pipeline(job: Job) -> None:
    with _PIPELINE_LOCK:
        _run(job)


def _run(job: Job) -> None:
    uid = job.uid
    # Cada ejecucion en vivo va a su propia carpeta: no se lee ni se pisa ningun resultado previo
    cache_dir = EN_VIVO_DIR / uid / datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    (cache_dir / "call1").mkdir(parents=True, exist_ok=True)
    (cache_dir / "call2").mkdir(parents=True, exist_ok=True)

    # --- 0. Cuota + key
    if not puede_llamar(MODELO, n=LLAMADAS_POR_USUARIO):
        raise RuntimeError(
            f"Cuota insuficiente para {MODELO}. Necesitas {LLAMADAS_POR_USUARIO} "
            f"llamadas y no hay cupo hoy. El tope diario del sitio se reinicia al cambiar de día."
        )
    # La clave viene del job (visitante) o de la variable DEMO_KEY del servidor; nunca de disco ni de os.environ
    clave = (job.api_key or "").strip() or os.environ.get("DEMO_KEY", "").strip()
    if not clave:
        raise RuntimeError("Falta la clave de OpenRouter: p\u00e9gala en la p\u00e1gina Cargar.")

    # --- 1. Datos del usuario
    job.etapa = "Cargando historial del usuario…"
    df_user = _load_user(uid)
    if df_user.empty:
        raise ValueError(f"Usuario {uid} no aparece en interactions_final.parquet")

    atribucion = _load_atribucion()
    if uid not in atribucion.get("usuarios", {}):
        raise ValueError(f"Usuario {uid} no está en atribucion.json")

    meta_idx = _load_meta()
    cutoff = _get_cutoff(uid, df_user)

    # --- 2. Contexto
    job.etapa = "Construyendo contexto (perfil + evidencia + atribución)…"
    # Mismo codigo validado (src/perfil.py) pero solo con el historial de este usuario:
    # cargar_historial() leeria el parquet completo (1.8M filas) en cada job.
    import perfil as _perfil
    _perfil.MAPA_JSON = str(cache_dir / "mapa_alias.json")  # no tocar el mapa global legacy
    ctx = _perfil.construir_contexto(uid, atribucion, {uid: _grupo_historial_usuario(uid)})

    # --- 3. Prompt Call #1
    job.etapa = "Preparando Call #1 (perfil del usuario)…"
    from prompts import construir_call1, construir_call2
    from llm_client import _call_openrouter

    sys1, usr1 = construir_call1(uid, ctx)
    (cache_dir / "call1" / "prompt_call1_system.txt").write_text(sys1, encoding="utf-8")
    (cache_dir / "call1" / "prompt_call1_user.txt").write_text(usr1, encoding="utf-8")

    # --- 4. Call #1
    job.etapa = "Llamando al LLM: Call #1 (perfil)…"
    resp1 = _call_openrouter(sys1, usr1, MODELO, MAX_TOKENS_CALL1, TEMPERATURE, REASONING, force=True,
                             user_id=uid, call_name="call1", api_key=clave)
    if resp1.content is None:
        raise RuntimeError(f"Call #1 falló (finish_reason={resp1.finish_reason})")
    if not resp1.cached:
        incrementar(MODELO, 1)
    try:
        perfil_json = json.loads(resp1.content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Call #1 devolvió JSON inválido: {e}")

    (cache_dir / "call1" / "perfil_v2.json").write_text(
        json.dumps(perfil_json, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "call1" / "response_raw.json").write_text(
        resp1.raw_json, encoding="utf-8")

    # --- 5. Verificar Call #1
    job.etapa = "Verificando fidelidad de Call #1…"
    mapa = {uid: {e["id"]: {"rating": e["rating"]} for e in ctx["evidencia"]}}
    v1 = _verificar_call1(uid, cache_dir, mapa)
    (cache_dir / "verif_call1.json").write_text(
        json.dumps(v1, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 6. Datos de los 5 productos + prompt Call #2
    job.etapa = "Preparando Call #2 (5 productos)…"
    parent_asins = [it["parent_asin"] for it in ctx["recomendaciones"]]
    producto = _cargar_reviews_productos(parent_asins, cutoff)

    sys2, usr2 = construir_call2(uid, ctx, perfil_json, cutoff, producto, meta_idx)
    (cache_dir / "call2" / "prompt_call2_system.txt").write_text(sys2, encoding="utf-8")
    (cache_dir / "call2" / "prompt_call2_user.txt").write_text(usr2, encoding="utf-8")

    # --- 7. Call #2
    job.etapa = "Llamando al LLM: Call #2 (explicación de 5 productos)…"
    resp2 = _call_openrouter(sys2, usr2, MODELO, MAX_TOKENS_CALL2, TEMPERATURE, REASONING, force=True,
                             user_id=uid, call_name="call2", api_key=clave)
    if resp2.content is None:
        raise RuntimeError(f"Call #2 falló (finish_reason={resp2.finish_reason})")
    if not resp2.cached:
        incrementar(MODELO, 1)
    try:
        explic = json.loads(resp2.content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Call #2 devolvió JSON inválido: {e}")

    (cache_dir / "call2" / "explicaciones_v2.json").write_text(
        json.dumps(explic, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "call2" / "response_raw.json").write_text(
        resp2.raw_json, encoding="utf-8")

    # --- 8. Verificar Call #2
    job.etapa = "Verificando fidelidad de Call #2…"
    v2 = _verificar_call2(uid, cache_dir, mapa)
    (cache_dir / "verif_call2.json").write_text(
        json.dumps(v2, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 9. Meta
    meta = {
        "uid": uid,
        "modelo": MODELO,
        "generado": datetime.datetime.now().isoformat(timespec="seconds"),
        "cutoff": int(cutoff),
        "call1": {
            "finish_reason": resp1.finish_reason, "cached": resp1.cached,
            "provider": resp1.provider, "tokens_in": resp1.tokens_prompt,
            "tokens_out": resp1.tokens_completion, "tokens_reasoning": resp1.tokens_reasoning,
            "veredicto": v1.get("veredicto_global"),
        },
        "call2": {
            "finish_reason": resp2.finish_reason, "cached": resp2.cached,
            "provider": resp2.provider, "tokens_in": resp2.tokens_prompt,
            "tokens_out": resp2.tokens_completion, "tokens_reasoning": resp2.tokens_reasoning,
            "veredicto": v2.get("veredicto_global"),
        },
    }
    (cache_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    job.etapa = "Completado"