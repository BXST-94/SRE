#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Servidor Flask local (puerto 5000).
Cuatro pestañas: /chatbot (inicio), /cargar, /historial, /api.
"""
import os as _os
import json as _json_mod
_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
def _P(*partes):
    return _os.path.join(_RAIZ, *partes)

import sys
from pathlib import Path
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, abort, Response

APP_DIR = Path(__file__).parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, _P())
sys.path.insert(0, str(APP_DIR / "chatbot_core"))

import data_loader as dl
import api_key_manager as akm
import jobs as jobs_mod

# Imports del chatbot
import chat_engine
import conversations

app = Flask(__name__)

MODELO_PRINCIPAL = "deepseek/deepseek-v4.1-flash-1017"


def _json_seguro(obj):
    txt = _json_mod.dumps(obj, ensure_ascii=False, allow_nan=False)
    return Response(txt, mimetype="application/json")


# ---------- Contexto global ----------
@app.context_processor
def inject_globals():
    q = akm.get_quota()
    return {
        "frase_defensa": dl.FRASE_DEFENSA,
        "limitacion": dl.LIMITACION,
        "quota_principal": {
            "restantes": q["por_modelo"][MODELO_PRINCIPAL]["restantes"],
            "limite": q["limite"],
        },
    }


# ---------- Redirección raíz (AHORA VA AL CHATBOT) ----------
@app.route("/")
def root():
    return redirect(url_for("chatbot_view"))


# ---------- /cargar ----------
@app.route("/cargar")
def cargar():
    usuarios = dl.listar_usuarios_disponibles()
    return render_template("cargar.html", active_tab="cargar", usuarios=usuarios)


# ---------- /historial ----------
@app.route("/historial")
def historial():
    uid_q = request.args.get("user")
    usuarios = dl.listar_usuarios_historial(extra_uid=uid_q)
    uid = uid_q or (usuarios[0] if usuarios else None)
    if not uid or uid not in usuarios:
        return render_template("error.html", active_tab="historial", usuarios=usuarios), 404
    if dl._ultima_corrida(uid) is None:
        return render_template("sin_ejecucion.html", active_tab="historial",
                               usuarios=usuarios, uid=uid), 200
    d = dl.cargar_todo(uid)
    return render_template("historial.html", active_tab="historial",
                           usuarios=usuarios, **d)


# ---------- /api ----------
@app.route("/api")
def api_view():
    q = akm.get_quota()
    return render_template("api.html", active_tab="api", quota=q)


# ---------- /chatbot ----------
@app.route("/chatbot")
def chatbot_view():
    usuarios = chat_engine.usuarios_demo()
    p = APP_DIR / "chatbot_core" / "data" / "categorias_resumen.json"
    if p.exists():
        cats_data = _json_mod.loads(p.read_text(encoding="utf-8"))
    else:
        cats_data = {"categorias": [], "total_items": 0}
        
    cats = []
    for c in cats_data.get("categorias", []):
        cats.append({"nombre": c.get("nombre", "?"), "n": int(c.get("items", 0) or 0)})
        
    return render_template("chatbot.html", active_tab="chatbot", 
                           usuarios=usuarios, 
                           categorias_lista=cats,
                           total_items=cats_data.get("total_items", 0),
                           n_categorias=len(cats),
                           modelo=chat_engine.MODELO)


# ---------- Endpoints JSON del Recomendador ----------
@app.post("/api/cargar_usuario")
def api_cargar_usuario():
    payload = request.get_json(silent=True) or {}
    uid = (payload.get("uid") or "").strip()
    if not uid or not dl.UID_RE.match(uid):
        return jsonify({"error": "uid inválido"}), 400
    if uid not in dl.usuarios_demo():
        return jsonify({"error": "usuario fuera de la lista de la demo"}), 400
    if not akm.puede_llamar(MODELO_PRINCIPAL, n=2):
        return jsonify({
            "error": f"Cuota insuficiente para {MODELO_PRINCIPAL}. "
                     f"Necesitas 2 llamadas y no hay cupo hoy. El tope diario del sitio se reinicia al cambiar de día."
        }), 429

    clave = str(payload.get("api_key") or "").strip()
    if clave and (not clave.startswith("sk-or-") or len(clave) > 200 or any(ch.isspace() for ch in clave)):
        return jsonify({"error": "La clave no tiene el formato esperado (empieza por sk-or-)."}), 400
    if not clave and not os.environ.get("DEMO_KEY", "").strip():
        return jsonify({"error": "Pega tu clave de OpenRouter en el campo de la parte superior de esta p\u00e1gina para analizar un usuario."}), 400

    job = jobs_mod.iniciar_job(uid, MODELO_PRINCIPAL, api_key=clave or None)
    return jsonify({"job_id": job.id, "uid": uid, "modelo": MODELO_PRINCIPAL})


@app.get("/api/job_status/<jid>")
def api_job_status(jid):
    j = jobs_mod.get_job(jid)
    if not j:
        return jsonify({"error": "job no encontrado"}), 404
    return jsonify({
        "status": j.status,
        "etapa": j.etapa,
        "error": j.error,
        "uid": j.uid,
        "modelo": j.modelo,
    })

@app.get("/api/cuota")
def api_cuota():
    return jsonify(akm.get_quota())

@app.post("/api/set_api_key")
def api_set_api_key():
    payload = request.get_json(silent=True) or {}
    key = payload.get("key", "")
    ok, msg = akm.set_api_key(key)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400
    return jsonify({"ok": True, "mensaje": msg, "preview": akm.key_preview()})

@app.get("/api/key_preview")
def api_key_preview():
    return jsonify({"preview": akm.key_preview()})


# ---------- Endpoints del Chatbot ----------
@app.post("/chatbot/chat")
def chatbot_chat():
    payload = request.get_json(silent=True) or {}
    uid = str(payload.get("uid") or "").strip()
    mensaje = str(payload.get("mensaje") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    conv_id = str(payload.get("conv_id") or "").strip() or None

    if not mensaje:
        return jsonify({"ok": False, "error": "mensaje vacio"}), 400

    if api_key and (not api_key.startswith("sk-or-") or len(api_key) > 200 or any(c.isspace() for c in api_key)):
        return jsonify({"ok": False, "error": "La clave no tiene el formato esperado (empieza por sk-or-)."}), 400

    if not api_key and not os.environ.get("DEMO_KEY", "").strip():
        return jsonify({"ok": False, "error": "Pega tu clave de OpenRouter en la barra lateral."}), 400

    try:
        resultado = chat_engine.procesar_turno(uid, mensaje, api_key or None, conv_id)
    except Exception as e:
        return jsonify({"ok": False, "error": "Error inesperado: %s" % e}), 500

    try:
        return _json_seguro(resultado), 200 if resultado.get("ok") else 502
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "respuesta no serializable"}), 500


@app.get("/chatbot/api/conversations")
def chatbot_api_listar_conversaciones():
    uid = request.args.get("uid", "")
    return _json_seguro(conversations.listar_conversaciones(uid))


@app.get("/chatbot/api/conversations/<conv_id>")
def chatbot_api_obtener_conversacion(conv_id):
    conv = conversations.obtener_conversacion(conv_id)
    if not conv:
        return jsonify({"ok": False, "error": "conversacion no encontrada"}), 404
    return _json_seguro(conv)


@app.delete("/chatbot/api/conversations/<conv_id>")
def chatbot_api_borrar_conversacion(conv_id):
    conversations.borrar_conversacion(conv_id)
    return _json_seguro({"ok": True})


# ---------- Legado: /?user=... ----------
@app.route("/legacy")
def legacy_redirect():
    uid = request.args.get("user", "")
    return redirect(url_for("historial", user=uid))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)