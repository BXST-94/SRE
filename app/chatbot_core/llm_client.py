# -*- coding: utf-8 -*-
"""Cliente OpenRouter para el chatbot. Adaptado de C:\\Amazon\\src\\llm_client.py.

Diferencias: no lee .env, no aplica tope diario, la api_key llega siempre por parametro,
y todas las rutas son relativas a esta carpeta.
"""
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_RPM_LIMIT = 20

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
SQLITE_PATH = CACHE_DIR / "llm.sqlite"
REGISTRO_PATH = CACHE_DIR / "llamadas_registro.jsonl"


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
    cached: bool = False


DDL = """
CREATE TABLE IF NOT EXISTS llm_calls(
    key TEXT PRIMARY KEY, ts TEXT, user_id TEXT, call TEXT,
    provider TEXT, model TEXT,
    tokens_in INTEGER, tokens_out INTEGER, reasoning_tokens INTEGER,
    response_raw TEXT, parsed_ok INTEGER, finish_reason TEXT
);
"""


def _con():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(SQLITE_PATH))
    con.executescript(DDL)
    return con


def init_db() -> None:
    _con().close()


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


def log_call(record: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(REGISTRO_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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
