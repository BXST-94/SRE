# -*- coding: utf-8 -*-
"""Persistencia de conversaciones en SQLite (data/conversations.sqlite).

Cada conversacion pertenece a un uid. El uid vacio se normaliza a "invitado".
Los turnos guardan el payload completo del bot (resumen, productos, historial)
para que la UI pueda re-renderizar conversaciones antiguas.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "conversations.sqlite"

DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    titulo TEXT,
    creada TEXT NOT NULL,
    actualizada TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_uid ON conversations(uid, actualizada DESC);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id TEXT NOT NULL,
    rol TEXT NOT NULL,
    texto TEXT,
    payload TEXT,
    ts TEXT NOT NULL,
    FOREIGN KEY(conv_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_turn_conv ON turns(conv_id, id);
"""


def _con():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript(DDL)
    return con


def init_db():
    _con().close()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_uid(uid):
    return (uid or "").strip() or "invitado"


def _titulo(msg):
    m = (msg or "").strip().replace("\n", " ")
    return (m[:60] + "…") if len(m) > 60 else (m or "Conversación")


def crear_conversacion(uid, primer_mensaje=""):
    conv_id = uuid.uuid4().hex[:12]
    ahora = _now()
    titulo = _titulo(primer_mensaje)
    con = _con()
    con.execute(
        "INSERT INTO conversations(id, uid, titulo, creada, actualizada) VALUES (?,?,?,?,?)",
        (conv_id, _norm_uid(uid), titulo, ahora, ahora))
    con.commit()
    con.close()
    return conv_id


def listar_conversaciones(uid, limite=50):
    con = _con()
    rows = con.execute(
        "SELECT id, uid, titulo, creada, actualizada FROM conversations "
        "WHERE uid=? ORDER BY actualizada DESC LIMIT ?",
        (_norm_uid(uid), limite)).fetchall()
    con.close()
    return [
        {"id": r[0], "uid": r[1], "titulo": r[2],
         "creada": r[3], "actualizada": r[4]}
        for r in rows
    ]


def obtener_conversacion(conv_id):
    con = _con()
    row = con.execute(
        "SELECT id, uid, titulo, creada, actualizada FROM conversations WHERE id=?",
        (conv_id,)).fetchone()
    if not row:
        con.close()
        return None
    turns = con.execute(
        "SELECT id, rol, texto, payload, ts FROM turns WHERE conv_id=? ORDER BY id",
        (conv_id,)).fetchall()
    con.close()
    return {
        "id": row[0], "uid": row[1], "titulo": row[2],
        "creada": row[3], "actualizada": row[4],
        "turnos": [
            {"id": t[0], "rol": t[1], "texto": t[2],
             "payload": json.loads(t[3]) if t[3] else {},
             "ts": t[4]}
            for t in turns
        ],
    }


def guardar_turno(conv_id, rol, texto, payload=None):
    ahora = _now()
    con = _con()
    con.execute(
        "INSERT INTO turns(conv_id, rol, texto, payload, ts) VALUES (?,?,?,?,?)",
        (conv_id, rol, texto,
         json.dumps(payload, ensure_ascii=False) if payload else None, ahora))
    con.execute("UPDATE conversations SET actualizada=? WHERE id=?", (ahora, conv_id))
    con.commit()
    con.close()


def borrar_conversacion(conv_id):
    con = _con()
    con.execute("DELETE FROM turns WHERE conv_id=?", (conv_id,))
    con.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    con.commit()
    con.close()


init_db()