#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
constants.py — Constantes compartidas entre módulos.
"""
import os as _os
_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # raiz de la carpeta presentacion
def _P(*partes):
    return _os.path.join(_RAIZ, *partes)

# URL base de OpenRouter
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Límites de rate limiting
DEFAULT_RPM_LIMIT = 20
SECONDS_BETWEEN_CALLS = 60.0 / 20  # 3 segundos

# Rutas por defecto
DEFAULT_SQLITE_PATH = _P("cache", "llm.sqlite")
DEFAULT_REGISTRO_PATH = _P("cache", "llamadas_registro.jsonl")