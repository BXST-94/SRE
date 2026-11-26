# -*- coding: utf-8 -*-
"""Busqueda local en el catalogo (sin API)."""
from pathlib import Path

import math

import pandas as pd

META = Path(__file__).resolve().parent / "data" / "meta_electronics.parquet"
_CACHE = None


def _limpio(v):
    """Devuelve None para NaN, NaT, +-inf; el resto tal cual (JSON-safe)."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _normalizar(registros):
    return [{k: _limpio(v) for k, v in r.items()} for r in registros]


def _cargar():
    global _CACHE
    if _CACHE is None:
        _CACHE = pd.read_parquet(META)
    return _CACHE


_IMG_CACHE = None


def _cargar_imagenes():
    global _IMG_CACHE
    if _IMG_CACHE is None:
        import json as _json
        p = Path(__file__).resolve().parent / "data" / "imagenes_productos.json"
        if p.exists():
            _IMG_CACHE = _json.loads(p.read_text(encoding="utf-8"))
        else:
            _IMG_CACHE = {}
    return _IMG_CACHE


def buscar(consulta, tope=20):
    """Devuelve hasta `tope` productos que cumplen la consulta.

    consulta: dict con claves opcionales:
      - keywords: list[str]
      - main_category: str
      - precio_max: float
    """
    df = _cargar().copy()
    if df is None or len(df) == 0:
        return []

    cat = str(consulta.get("main_category") or "").strip().lower()
    if cat:
        df_cat = df[df["main_category"].astype(str).str.lower() == cat]
        if len(df_cat) > 0:
            df = df_cat
        # si el filtro por categoria deja el resultado vacio, se relaja: el LLM puede
        # proponer una categoria que no coincide exactamente con las del catalogo.

    pmax = consulta.get("precio_max")
    if pmax is not None:
        try:
            pmax = float(pmax)
            precios = pd.to_numeric(df["price"], errors="coerce")
            df = df[(precios.isna()) | (precios <= pmax)]
        except (TypeError, ValueError):
            pass

    kws = [str(k).lower().strip() for k in (consulta.get("keywords") or []) if str(k).strip()]
    if kws:
        texto = (df["title"].astype(str).str.lower() + " "
                 + df["categories"].astype(str).str.lower() + " "
                 + df["main_category"].astype(str).str.lower())
        mask = pd.Series(False, index=df.index)
        for k in kws:
            mask |= texto.str.contains(k, regex=False, na=False)
        df = df[mask]

    if len(df) == 0:
        return []

    df["_n"] = pd.to_numeric(df["rating_number"], errors="coerce").fillna(0)
    df["_r"] = pd.to_numeric(df["average_rating"], errors="coerce").fillna(0)
    df = df.sort_values(["_n", "_r"], ascending=False).head(tope)
    df = df.drop(columns=["_n", "_r"])

    cols = [c for c in ("parent_asin", "title", "main_category", "price",
                        "average_rating", "rating_number", "store") if c in df.columns]
    df = df[cols]
    registros = _normalizar(df.to_dict("records"))
    imgs = _cargar_imagenes()
    for r in registros:
        r["imagen"] = imgs.get(r.get("parent_asin"))
    return registros
