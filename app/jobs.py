#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs.py — Registro de jobs de carga en vivo, en memoria + thread runner.

El progreso que ve el usuario en el navegador es "fake" (basado en tiempo,
según el cronograma 5→30→90→99%). Este módulo solo reporta status real
(pending / running / done / error) y la etapa actual.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

_LOCK = threading.Lock()
_JOBS: dict[str, "Job"] = {}


@dataclass
class Job:
    id: str
    uid: str
    modelo: str
    status: str = "pending"   # pending | running | done | error
    etapa: str = "En cola"
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    # Clave de OpenRouter del visitante: solo en memoria, nunca en disco y fuera del repr
    api_key: Optional[str] = field(default=None, repr=False)


def get_job(jid: str) -> Optional[Job]:
    with _LOCK:
        return _JOBS.get(jid)


def _nuevo(uid: str, modelo: str) -> Job:
    jid = uuid.uuid4().hex
    j = Job(id=jid, uid=uid, modelo=modelo)
    with _LOCK:
        _JOBS[jid] = j
    return j


def _runner(j: Job) -> None:
    from live_pipeline import ejecutar_pipeline  # import perezoso
    with _LOCK:
        j.status = "running"
        j.etapa = "Inicializando pipeline…"
    try:
        try:
            ejecutar_pipeline(j)
        finally:
            j.api_key = None  # la clave del visitante no sobrevive al job
        with _LOCK:
            j.status = "done"
            j.etapa = "Completado"
            j.finished_at = time.time()
    except Exception as e:
        with _LOCK:
            j.status = "error"
            j.etapa = "Error"
            j.error = f"{type(e).__name__}: {e}"
            j.finished_at = time.time()


def iniciar_job(uid: str, modelo: str, api_key: Optional[str] = None) -> Job:
    j = _nuevo(uid, modelo)
    j.api_key = api_key
    t = threading.Thread(target=_runner, args=(j,), daemon=True, name=f"job-{j.id[:6]}")
    t.start()
    return j


def set_etapa(jid: str, texto: str) -> None:
    with _LOCK:
        j = _JOBS.get(jid)
        if j:
            j.etapa = texto