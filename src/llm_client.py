#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_client.py — Cliente HTTP OpenRouter con caché, rate limiting, compuerta de aprobación
y registro. ÚNICA fuente de acceso a OpenRouter en el proyecto.

Compuerta de aprobación:
  hash_aprobacion = sha256(modelo + "\n" + system + "\n" + user + "\n" + temperature +
                           "\n" + reasoning_effort + "\n" + max_tokens)[:8]
  Se calcula leyendo cache/prompt_call1_{system,user}.txt del disco, no de memoria.
"""
import os as _os
_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # raiz de la carpeta presentacion
def _P(*partes):
    return _os.path.join(_RAIZ, *partes)

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import requests

from constants import OPENROUTER_BASE_URL, DEFAULT_RPM_LIMIT

SQLITE_PATH = _P("cache", "llm.sqlite")
REGISTRO_PATH = _P("cache", "llamadas_registro.jsonl")
PROMPT_CALL1_SYSTEM = _P("cache", "prompt_call1_system.txt")
PROMPT_CALL1_USER = _P("cache", "prompt_call1_user.txt")


@dataclass
class LLMResponse:
    raw_json: str
    content: Optional[str]
    finish_reason: Optional[str]
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_reasoning: int = 0
    provider: Optional[str] = None
    model: Optional[str] = None
    cost_usd: float = 0.0
    cached: bool = False


# ===================== SQLite =====================

DDL = """
CREATE TABLE IF NOT EXISTS llm_calls(
    key TEXT PRIMARY KEY, ts TEXT, user_id TEXT, call TEXT,
    provider TEXT, model TEXT,
    tokens_in INTEGER, tokens_out INTEGER, reasoning_tokens INTEGER,
    response_raw TEXT, parsed_ok INTEGER, finish_reason TEXT
);
CREATE TABLE IF NOT EXISTS model_daily_usage(
    date TEXT, model TEXT, calls INTEGER, PRIMARY KEY (date, model)
);
"""


def _con():
    Path(_P("cache")).mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(SQLITE_PATH)
    con.executescript(DDL)
    return con


def init_db() -> None:
    _con().close()


def hash_aprobacion(model: str, system: str, user: str, temperature: float,
                    reasoning_effort: str, max_tokens: int) -> str:
    material = f"{model}\n{system}\n{user}\n{temperature}\n{reasoning_effort}\n{max_tokens}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]


def cargar_prompts_aprobados(hash_esperado: str, model: str, temperature: float,
                             reasoning_effort: str, max_tokens: int,
                             system_path: str = PROMPT_CALL1_SYSTEM,
                             user_path: str = PROMPT_CALL1_USER):
    """
    Lee los archivos del disco, verifica que el hash calculado coincide con hash_esperado
    y devuelve (system, user). Si no coincide, lanza RuntimeError.
    """
    if not os.path.exists(system_path) or not os.path.exists(user_path):
        raise RuntimeError(f"Faltan archivos de prompt: {system_path} / {user_path}")
    system = Path(system_path).read_text(encoding="utf-8")
    user = Path(user_path).read_text(encoding="utf-8")
    h = hash_aprobacion(model, system, user, temperature, reasoning_effort, max_tokens)
    if h != hash_esperado:
        raise RuntimeError(f"Hash de aprobación no coincide: esperado {hash_esperado}, calculado {h}")
    return system, user


def cache_key(model: str, system: str, user: str, temperature: float,
              reasoning_effort: str) -> str:
    material = f"{model}\n{system}\n{user}\n{temperature}\n{reasoning_effort}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_cached_response(key: str):
    con = _con()
    row = con.execute(
        "SELECT response_raw, provider, parsed_ok, finish_reason FROM llm_calls WHERE key=?",
        (key,)).fetchone()
    con.close()
    return row


# ===================== Uso diario por modelo =====================

def get_model_usage(model: str) -> int:
    con = _con()
    row = con.execute(
        "SELECT calls FROM model_daily_usage WHERE date=? AND model=?",
        (date.today().isoformat(), model)).fetchone()
    con.close()
    return row[0] if row else 0


def increment_model_usage(model: str) -> None:
    con = _con()
    con.execute(
        "INSERT INTO model_daily_usage(date, model, calls) VALUES (?,?,1) "
        "ON CONFLICT(date,model) DO UPDATE SET calls=calls+1",
        (date.today().isoformat(), model))
    con.commit()
    con.close()


def log_call(record: dict) -> None:
    with open(REGISTRO_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ===================== Llamada HTTP =====================


def _cargar_env():
    """Carga C:\\Amazon\\.env en os.environ si OPENROUTER_API_KEY no esta."""
    env_path = Path(_P(".env"))
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and not os.environ.get(k):
            os.environ[k] = v


def _call_openrouter(
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    temperature: float,
    reasoning_effort: str,
    user_id: str = "",
    call_name: str = "call1",
    force: bool = False,
    api_key: Optional[str] = None,
) -> LLMResponse:
    """
    Llama a OpenRouter. Sin failover ni reintentos.
    - Caché: por (model, system, user, temperature, reasoning_effort).
    - 429: registro, no caché, retorna LLMResponse con content=None.
    - finish_reason=length: registro como 'configuracion', no caché.
    - max_tokens demasiado bajo: ídem.
    """
    # Sitio publico: la clave llega por parametro (del visitante) y no se lee de .env ni de os.environ
    api_key = (api_key or "").strip()
    if not api_key:
        raise RuntimeError("Falta la clave de OpenRouter (api_key)")

    key = cache_key(model, system, user, temperature, reasoning_effort)
    if not force:
        cached = get_cached_response(key)
        if cached:
            raw, provider, parsed_ok, finish_reason = cached
            data = json.loads(raw) if raw else {}
            content = None
            try:
                content = data["choices"][0]["message"].get("content")
            except (KeyError, IndexError, TypeError):
                pass
            usage = data.get("usage", {}) or {}
            return LLMResponse(
                raw_json=raw, content=content, finish_reason=finish_reason,
                tokens_prompt=usage.get("prompt_tokens", 0) or 0,
                tokens_completion=usage.get("completion_tokens", 0) or 0,
                tokens_reasoning=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
                provider=provider, model=model, cached=True)

    # Rate limiting: 20 RPM
    time.sleep(60.0 / DEFAULT_RPM_LIMIT)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        resp = requests.post(OPENROUTER_BASE_URL, headers=headers, json=payload, timeout=180)
    except Exception as e:
        log_call({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "user_id": user_id,
                  "call": call_name, "status": "error_red", "model": model,
                  "detail": str(e)[:300]})
        return LLMResponse(raw_json="", content=None, finish_reason=None, model=model)

    if resp.status_code == 429:
        log_call({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "user_id": user_id,
                  "call": call_name, "status": "http_429", "model": model,
                  "detail": resp.text[:300]})
        return LLMResponse(raw_json="", content=None, finish_reason="rate_limited", model=model)

    if resp.status_code != 200:
        log_call({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "user_id": user_id,
                  "call": call_name, "status": f"http_{resp.status_code}", "model": model,
                  "detail": resp.text[:300]})
        return LLMResponse(raw_json="", content=None, finish_reason=None, model=model)

    data = resp.json()
    raw = json.dumps(data, ensure_ascii=False)
    provider = data.get("provider")
    usage = data.get("usage", {}) or {}
    try:
        choice = data["choices"][0]
        content = choice["message"].get("content")
        finish_reason = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError):
        content, finish_reason = None, "invalid"

    llm_resp = LLMResponse(
        raw_json=raw, content=content, finish_reason=finish_reason,
        tokens_prompt=usage.get("prompt_tokens", 0) or 0,
        tokens_completion=usage.get("completion_tokens", 0) or 0,
        tokens_reasoning=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
        provider=provider, model=model, cached=False,
    )

    # Solo cachear si finish_reason=stop y hay content
    if finish_reason == "stop" and content:
        con = _con()
        con.execute(
            "INSERT OR REPLACE INTO llm_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, time.strftime("%Y-%m-%d %H:%M:%S"), user_id, call_name,
             provider or "openrouter", model, llm_resp.tokens_prompt, llm_resp.tokens_completion,
             llm_resp.tokens_reasoning, raw, 1, finish_reason))
        con.commit()
        con.close()

    log_call({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "user_id": user_id,
              "call": call_name, "status": "ok" if finish_reason == "stop" else finish_reason,
              "model": model, "provider": provider,
              "tokens_in": llm_resp.tokens_prompt, "tokens_out": llm_resp.tokens_completion,
              "tokens_reasoning": llm_resp.tokens_reasoning,
              "finish_reason": finish_reason, "cached": False})

    return llm_resp


init_db()