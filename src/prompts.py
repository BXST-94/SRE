#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompts.py — Builders de Call #1 (perfil) y Call #2 (explicación)."""

import json
from typing import Any, Dict, List, Tuple

from prompts_text import SYSTEM_PERFIL, SYSTEM_EXPLICA
from textos import limpiar_texto, recortar_texto, recortar_titulo


# ===================== Call #1 =====================

def construir_call1(user_id: str, ctx: Dict[str, Any]) -> Tuple[str, str]:
    """System y user para Call #1 (perfil)."""
    perfil = ctx["perfil"]
    ev = ctx["evidencia"]
    partes = [
        "Evidencia del usuario (SOLO lo listado aquí; no añadir nada más). "
        f"Resumen de actividad: {perfil['n_interacciones']} interacciones verificadas | "
        f"rating medio {perfil['rating_medio']} | categorías frecuentes (NO usarlas en la salida): "
        f"{', '.join(perfil['categorias_frecuentes'])} | compras verificadas: "
        f"{perfil['pct_verified_purchase']*100:.0f}%.\n",
        "\nReseñas del usuario (ID | rating | votos de útil | split):\n",
    ]
    for e in ev:
        titulo = recortar_titulo(limpiar_texto(e.get("title", "")), 120)
        texto = recortar_texto(limpiar_texto(e.get("text", "")), 500)
        partes.append(
            f"  {e['id']}: {e['rating']}★ | helpful_vote={e['helpful_vote']} | "
            f"split={e['split']} | '{titulo}' — \"{texto}\"\n"
        )
    partes.append("\nDevuelve EXCLUSIVAMENTE el JSON pedido en el sistema.")
    return SYSTEM_PERFIL, "".join(partes)


# ===================== Call #2 =====================

def _precio_txt(precio) -> str:
    if precio is None or (isinstance(precio, float) and precio != precio) or str(precio).lower() == "nan":
        return ""
    return f", precio aprox.: {precio}"


def _resenas_producto(rs: List[Dict], cutoff_ts: int, n_pos: int = 2, n_neg: int = 1):
    """Filtra reseñas del producto con timestamp < cutoff_ts. Positivas por helpful_vote desc."""
    pos = sorted(
        [r for r in rs if r["rating"] >= 4 and r["timestamp"] < cutoff_ts],
        key=lambda r: r["helpful_vote"], reverse=True)[:n_pos]
    neg = sorted(
        [r for r in rs if r["rating"] <= 2 and r["timestamp"] < cutoff_ts],
        key=lambda r: r["helpful_vote"], reverse=True)[:n_neg]
    return pos, neg


def construir_call2(
    user_id: str,
    ctx: Dict[str, Any],
    perfil_json: Dict,
    cutoff_ts: int,
    producto: Dict[str, List[Dict]],
    meta_idx: Dict[str, Dict],
) -> Tuple[str, str]:
    """
    System y user para Call #2 (explicación por producto).

    ctx["recomendaciones"] debe tener 5 ítems con:
        rank, parent_asin, logit, base_rank, cobertura_top3,
        razones: [{id (P#), peso, delta_logit, split, removed_title, removed_rating, removed_text}]
    producto[parent_asin]: lista de dicts con rating, helpful_vote, timestamp, title, text
    meta_idx[parent_asin]: {title, main_category, price, store}
    """
    partes = [
        "PERFIL DEL USUARIO (salida de Call #1, úsalo como fuente de 'aspecto'):\n",
        json.dumps(perfil_json, ensure_ascii=False, indent=2),
        "\n\n",
        "INSTRUCCIONES ESPECÍFICAS:\n",
        "- Devuelve un elemento por cada uno de los 5 ítems, en el mismo orden.\n",
        "- Los IDs P# son reseñas del usuario (aparecen en las razones de atribución).\n",
        "- Los IDs R# son reseñas del producto. R1, R2... son positivas; el último R# (si existe) es la negativa.\n",
        "- En 'coincide_con', el 'aspecto' debe copiarse EXACTAMENTE de una preferencia del perfil de arriba.\n",
        "- En 'por_que_el_modelo' cita los [P#] con su peso tal como aparece abajo.\n",
        "- Si un ítem no tiene reseñas negativas, 'ten_en_cuenta' = null.\n\n",
        "ATRIBUCIÓN DEL MODELO Y RESEÑAS DEL PRODUCTO:\n",
    ]

    recs = ctx.get("recomendaciones", [])
    for it in recs:
        pa = it["parent_asin"]
        m = meta_idx.get(pa, {})
        titulo = recortar_titulo(limpiar_texto(m.get("title", pa)), 120)
        categoria = m.get("main_category", "?")
        precio = _precio_txt(m.get("price"))

        partes.append(
            f"\n### Ítem #{it['rank']}: {titulo} (categoría: {categoria}{precio})\n"
            f"[parent_asin={pa} | score={it['logit']} | rank histórico={it['base_rank']} | "
            f"cobertura_top3={it['cobertura_top3']:.2f}]\n"
            "Razones de atribución (reseñas del usuario que el modelo usó para este ítem):\n"
        )
        for r in it.get("razones", []):
            texto_r = recortar_texto(limpiar_texto(r.get("removed_text", "")), 300)
            titulo_r = recortar_titulo(limpiar_texto(r.get("removed_title", "")), 100)
            partes.append(
                f"  [{r['id']}] peso {r['peso']:.2f}, Δlogit {r['delta_logit']:+.2f}, "
                f"split={r.get('split', '?')} — '{titulo_r}' — {r.get('removed_rating', '?')}★ — "
                f"\"{texto_r}\"\n"
            )

        rs = producto.get(pa, [])
        pos, neg = _resenas_producto(rs, cutoff_ts, n_pos=2, n_neg=1)
        partes.append("Reseñas del producto (timestamp < corte del usuario):\n")
        if not pos and not neg:
            partes.append("  (Sin reseñas del producto anteriores al corte del usuario.)\n")
            partes.append(
                "  → 'coincide_con' = [], 'ten_en_cuenta' = null; en 'por_que_el_modelo' "
                "di solo qué [P#] pesaron y con qué peso.\n"
            )
            continue

        for i, r in enumerate(pos, 1):
            texto_r = recortar_texto(limpiar_texto(r.get("text", "")), 400)
            titulo_r = recortar_titulo(limpiar_texto(r.get("title", "")), 100)
            partes.append(
                f"  R{i}. ({r['rating']}★, helpful_vote={r['helpful_vote']}) "
                f"\"{texto_r}\" — título: '{titulo_r}'\n"
            )
        if neg:
            r = neg[0]
            idx_neg = len(pos) + 1
            texto_r = recortar_texto(limpiar_texto(r.get("text", "")), 400)
            titulo_r = recortar_titulo(limpiar_texto(r.get("title", "")), 100)
            partes.append(
                f"  R{idx_neg}. ({r['rating']}★, helpful_vote={r['helpful_vote']}) "
                f"\"{texto_r}\" — título: '{titulo_r}'\n"
            )
        else:
            partes.append(
                "  (No hay reseñas negativas del producto con timestamp anterior al corte del usuario; "
                "'ten_en_cuenta' = null con ese motivo.)\n"
            )

    partes.append(
        "\nDevuelve EXCLUSIVAMENTE el JSON con los 5 ítems, sin texto adicional."
    )
    return SYSTEM_EXPLICA, "".join(partes)