# -*- coding: utf-8 -*-
"""
perfil.py — Contexto por usuario: perfil, evidencia (P1..Pn), recomendaciones con alias,
mapa v2, y cálculo de evidencia_insuficiente EN CÓDIGO (no en el LLM).
"""
import os as _os
_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # raiz de la carpeta presentacion
def _P(*partes):
    return _os.path.join(_RAIZ, *partes)

import json
import pandas as pd
from textos import limpiar_texto, recortar_texto, recortar_titulo

PARQUET = _P("data", "processed", "interactions_final.parquet")
MAPA_JSON = _P("cache", "evidencia_mapa_v2.json")


def cargar_historial():
    """Carga interacciones train+valid (anti-leakage: NUNCA test)."""
    df = pd.read_parquet(PARQUET, columns=[
        "user_id", "review_id", "parent_asin", "asin", "rating", "title", "text",
        "timestamp", "split", "helpful_vote", "verified_purchase",
        "item_main_category", "item_title", "seq_idx",
    ])
    grupos = {}
    for uid, g in df.groupby("user_id", sort=False):
        grupos[uid] = g[g.split != "test"].sort_values(["timestamp", "seq_idx"], kind="mergesort")
    return grupos


def perfil_usuario(g):
    """Estadísticas resumen del usuario (las que usa el prompt)."""
    if len(g) == 0:
        return {"n_interacciones": 0, "rating_medio": 0.0,
                "categorias_frecuentes": [], "pct_verified_purchase": 0.0}
    cats = g.item_main_category.value_counts().head(2).index.tolist()
    return {
        "n_interacciones": int(len(g)),
        "rating_medio": round(float(g.rating.mean()), 2),
        "categorias_frecuentes": [str(c) for c in cats],
        "pct_verified_purchase": round(float(g.verified_purchase.mean()), 2),
    }


def _guardar_mapa(user_id: str, mapa: dict) -> None:
    try:
        with open(MAPA_JSON, encoding="utf-8") as f:
            todo = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        todo = {}
    todo[user_id] = mapa
    with open(MAPA_JSON, "w", encoding="utf-8") as f:
        json.dump(todo, f, ensure_ascii=False, indent=2)


def construir_contexto(user_id: str, atribucion: dict, grupos: dict) -> dict:
    """Devuelve perfil, evidencia con alias P1..Pn, recomendaciones con alias y mapa."""
    g = grupos.get(user_id)
    if g is None or len(g) == 0:
        return {"user_id": user_id, "perfil": {}, "evidencia": [], "recomendaciones": [], "mapa": {}}

    perfil = perfil_usuario(g)
    g_sorted = g.sort_values(["timestamp", "seq_idx"], kind="mergesort")

    evidencia, mapa, pa_to_alias = [], {}, {}
    for idx, row in enumerate(g_sorted.itertuples(), 1):
        alias = f"P{idx}"
        item = {
            "id": alias,
            "review_id": int(row.review_id),
            "parent_asin": row.parent_asin,
            "rating": float(row.rating),
            "helpful_vote": int(row.helpful_vote),
            "title": limpiar_texto(str(row.title)) if pd.notna(row.title) else "",
            "text": limpiar_texto(str(row.text)) if pd.notna(row.text) else "",
            "split": str(row.split),
            "timestamp_ms": int(row.timestamp),
        }
        evidencia.append(item)
        mapa[alias] = {
            "review_id": item["review_id"],
            "parent_asin": item["parent_asin"],
            "timestamp_ms": item["timestamp_ms"],
            "rating": item["rating"],
            "helpful_vote": item["helpful_vote"],
            "split": item["split"],
            "titulo_mostrado": recortar_titulo(item["title"], 120),
            "texto_mostrado": recortar_texto(item["text"], 500),
        }
        pa_to_alias.setdefault(item["parent_asin"], alias)

    _guardar_mapa(user_id, mapa)

    # Recomendaciones con alias resueltos por parent_asin
    recomendaciones = []
    for it in atribucion.get("usuarios", {}).get(user_id, []):
        razones = []
        for r in it.get("razones", []):
            alias = pa_to_alias.get(r.get("removed_parent_asin"))
            if not alias:
                continue
            razones.append({
                "id": alias,
                "removed_parent_asin": r["removed_parent_asin"],
                "removed_title": r.get("title", ""),
                "removed_rating": r.get("rating", 0),
                "peso": round(float(r["weight"]), 2),
                "delta_logit": round(float(r["delta_logit"]), 3),
                "removed_text": r.get("text", ""),
                "split": r.get("split", "train"),
            })
        cobertura = round(sum(r["peso"] for r in razones), 2)
        recomendaciones.append({
            "rank": it["rank"],
            "parent_asin": it["parent_asin"],
            "logit": round(float(it["logit"]), 3),
            "base_rank": it["base_rank"],
            "cobertura_top3": cobertura,
            "razones": razones,
        })

    return {"user_id": user_id, "perfil": perfil, "evidencia": evidencia,
            "recomendaciones": recomendaciones, "mapa": mapa}


def calcular_evidencia_insuficiente(perfil_json: dict) -> bool:
    """
    Regla en código: true si <3 preferencias o <3 advertencias.
    El LLM ya NO decide este campo (se quitó del esquema en prompts_text.py).
    """
    if not isinstance(perfil_json, dict):
        return True
    prefs = perfil_json.get("preferencias") or []
    advs = perfil_json.get("advertencias") or []
    return (len(prefs) < 3) or (len(advs) < 3)