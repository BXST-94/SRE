#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
meta_index.py — Índice de metadatos cacheado con lru_cache.
load_meta() -> dict {parent_asin: {"title", "main_category", "price"}}
Devuelve EXACTAMENTE los mismos valores y tipos que la lectura original (NaN, no None).
"""
import os as _os
_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # raiz de la carpeta presentacion
def _P(*partes):
    return _os.path.join(_RAIZ, *partes)

import functools
import pandas as pd
from pathlib import Path

CACHE = Path(_P("cache"))
META_INDEX = CACHE / "meta_index.parquet"


@functools.lru_cache(maxsize=1)
def load_meta() -> dict:
    """Carga el índice de metadatos desde cache/meta_index.parquet."""
    if not META_INDEX.exists():
        return {}
    df = pd.read_parquet(META_INDEX)
    # Convertir a dict preservando NaN (no convertir a None)
    return df.set_index("parent_asin")[["title", "main_category", "price"]].to_dict("index")


def invalidate_cache():
    """Invalida la caché (útil si se regenera meta_index.parquet)."""
    load_meta.cache_clear()


if __name__ == "__main__":
    m = load_meta()
    print(f"Cargados {len(m)} productos")
    for k in list(m.keys())[:3]:
        print(k, m[k])