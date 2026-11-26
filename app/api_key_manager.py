#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_key_manager.py (version del sitio publico): cuota diaria global por modelo.

Diferencias con el proyecto original:
- La clave de OpenRouter NUNCA se guarda en disco ni en os.environ. Cada visitante la envia con su
  analisis y vive solo en memoria mientras dura el job (ver jobs.py y live_pipeline.py).
- No existe ningun archivo de clave compartido entre visitantes.
- El tope diario sale de la variable de entorno LIMITE_DIARIO (por defecto 100 llamadas por modelo).
  La cuota se guarda en cache/cuota_api.json y se reinicia al cambiar de dia.
"""

import datetime
import json
import os
import threading
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "cache"
QUOTA_FILE = CACHE / "cuota_api.json"


def _leer_limite() -> int:
    try:
        valor = int(os.environ.get("LIMITE_DIARIO", "100"))
    except ValueError:
        return 100
    return valor if valor > 0 else 100


LIMITE_POR_MODELO = _leer_limite()
MODELOS = [
    "deepseek/deepseek-v4.1-flash-1017",
    "meta-llama/llama-3.3-70b-instruct:free",
]

_LOCK = threading.Lock()


def _hoy() -> str:
    return datetime.date.today().isoformat()


def _cargar() -> dict:
    with _LOCK:
        data = {}
        if QUOTA_FILE.exists():
            try:
                data = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        if data.get("fecha") != _hoy():
            data = {"fecha": _hoy(), "por_modelo": {}}
            QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
            QUOTA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        data.setdefault("por_modelo", {})
        return data


def _guardar(data: dict) -> None:
    with _LOCK:
        QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUOTA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_quota() -> dict:
    data = _cargar()
    usadas = data.get("por_modelo", {})
    por_modelo = {}
    for m in MODELOS:
        u = int(usadas.get(m, 0))
        por_modelo[m] = {
            "usadas": u,
            "restantes": max(0, LIMITE_POR_MODELO - u),
            "limite": LIMITE_POR_MODELO,
        }
    return {"fecha": data["fecha"], "limite": LIMITE_POR_MODELO, "por_modelo": por_modelo}


def puede_llamar(modelo: str, n: int = 1) -> bool:
    data = _cargar()
    usadas = int(data.get("por_modelo", {}).get(modelo, 0))
    return (LIMITE_POR_MODELO - usadas) >= n


def incrementar(modelo: str, n: int = 1) -> int:
    data = _cargar()
    data.setdefault("por_modelo", {})
    data["por_modelo"][modelo] = int(data["por_modelo"].get(modelo, 0)) + n
    _guardar(data)
    return data["por_modelo"][modelo]


def get_api_key() -> str:
    """Compatibilidad con el codigo original: el sitio publico no guarda ninguna clave en el servidor."""
    return ""


def key_preview() -> str:
    return "(la clave no se guarda en el servidor)"


def set_api_key(nueva: str) -> tuple:
    return False, "Desactivado en el sitio p\u00fablico: la clave se env\u00eda con cada an\u00e1lisis desde la p\u00e1gina Cargar y no se guarda en el servidor."
