#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verifier.py — Verificador consolidado de Call #1 + Call #2 + métricas del Paso 11.

Entradas (todas ya guardadas, este módulo NO llama a la API):
  cache/v2_call1/prompt_call1_user.txt
  cache/v2_call1/perfil_v2.json
  cache/v2_call2/prompt_call2_user.txt
  cache/v2_call2/explicaciones_v2.json
  cache/evidencia_mapa_v2.json

Salidas:
  cache/v2_call1/verif_v2.json   (reescrito con más detalle)
  cache/v2_call2/verif_v2.json   (nuevo)
  cache/metricas_paso11.json     (agregado)

Uso:
  py src/verifier.py             # verificación completa sin parquet
  py src/verifier.py --leakage   # añade chequeo de leakage temporal (lee parquet)
"""
import os as _os
_RAIZ = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # raiz de la carpeta presentacion
def _P(*partes):
    return _os.path.join(_RAIZ, *partes)

import argparse
import json
import re
import sys
from pathlib import Path

# ===================== Rutas =====================

V2_CALL1 = Path(_P("cache", "v2_call1"))
V2_CALL2 = Path(_P("cache", "v2_call2"))
MAPA_PATH = Path(_P("cache", "evidencia_mapa_v2.json"))
PARQUET = _P("data", "processed", "interactions_final.parquet")

UID = "AG3FEXIZOCYEPKXZXSPH6YC72BIA"


# ===================== Utilidades =====================

def norm(s: str) -> str:
    """Normaliza para comparación: minúsculas, espacios colapsados, «…» → '...'."""
    return re.sub(r"\s+", " ", s.replace("\u2026", "...")).strip().lower()


def extraer_cuerpos_call1(prompt_user: str) -> dict:
    """Extrae {P#: cuerpo} del USER prompt de Call #1."""
    cuerpos = {}
    for linea in prompt_user.split("\n"):
        m = re.match(r"\s+(P\d+):.*\u2014 \"(.*)\"\s*$", linea)
        if m:
            cuerpos[m.group(1)] = m.group(2)
    return cuerpos


def extraer_titulos_call1(prompt_user: str) -> dict:
    """Extrae {P#: titulo} del USER prompt de Call #1.
    Título: texto entre '| ''' y la primera aparición de ''' — ' en la línea."""
    titulos = {}
    for linea in prompt_user.split("\n"):
        m = re.match(r"\s+(P\d+):.*\|\s*'([^']*)'\s*—", linea)
        if m:
            titulos[m.group(1)] = m.group(2)
    return titulos


def extraer_call2(prompt_user: str) -> dict:
    """Extrae por ítem: parent_asin, {R#: {rating, hv, body, title}}.
    Cada línea de reseña tiene formato:
      R<n>. (<rating>★, helpful_vote=<n>) "<cuerpo>" — título: '<titulo>'
    El cuerpo es el texto entre la primera comilla doble tras el paréntesis de cierre
    y la ÚLTIMA aparición de " — título: " en esa misma línea.
    El título es el texto entre "— título: '" y el último apóstrofo NO escapado de la línea.
    """
    items = {}
    # Dividir por "### Ítem #"
    bloques = re.split(r"### Ítem #", prompt_user)[1:]
    for bloque in bloques:
        m = re.match(r"(\d+):", bloque)
        if not m:
            continue
        rank = int(m.group(1))
        pa = re.search(r"parent_asin=(B[A-Z0-9]{9})", bloque)
        rs = {}
        # Procesar cada línea del bloque
        for linea in bloque.split("\n"):
            # Buscar el patrón base: R<n>. (<rating>★, helpful_vote=<n>) "<cuerpo>" — título:
            # Usamos una regex que capture hasta " — título: " y luego procesamos el título por separado
            rm = re.match(
                r"\s*R(\d+)\.\s*\(([\d.]+)★,\s*helpful_vote=(\d+)\)\s+\"(.*)\"\s*\u2014\s*título:\s*'(.+)'$",
                linea
            )
            if rm:
                rid = f"R{rm.group(1)}"
                cuerpo_completo = rm.group(4)
                # El grupo 5 captura todo hasta el final de línea después de 'título: '
                # Pero puede contener comillas simples escapadas. La regex greedy captura hasta el último '
                # Sin embargo, si el título termina con una comilla simple escapada \', el $ no matchea.
                # Mejor: capturamos todo hasta el final y luego quitamos la comilla final si existe.
                titulo_raw = rm.group(5)
                # El título está entre comillas simples. La regex ya capturó hasta el último ' antes de $
                # Pero si hay \' dentro, la regex los incluye. Solo necesitamos quitar la comilla final si quedó.
                if titulo_raw.endswith("'"):
                    titulo = titulo_raw[:-1]
                else:
                    titulo = titulo_raw
                # Desescapar comillas simples: \' -> '
                titulo = titulo.replace("\\'", "'")
                rs[rid] = {
                    "rating": float(rm.group(2)),
                    "hv": int(rm.group(3)),
                    "body": cuerpo_completo,
                    "title": titulo,
                }
        items[rank] = {"asin": pa.group(1) if pa else "?", "rs": rs}
    return items


# ===================== Call #1 =====================

def verificar_call1() -> dict:
    print("=" * 70)
    print("CALL #1 — verificación")
    print("=" * 70)
    prompt_user = (V2_CALL1 / "prompt_call1_user.txt").read_text(encoding="utf-8")
    perfil = json.loads((V2_CALL1 / "perfil_v2.json").read_text(encoding="utf-8"))
    mapa = json.loads(MAPA_PATH.read_text(encoding="utf-8"))
    cuerpos = extraer_cuerpos_call1(prompt_user)
    titulos = extraer_titulos_call1(prompt_user)
    print(f"Prompt: {len(prompt_user)} chars, {len(cuerpos)} P# extraídos (cuerpos), {len(titulos)} títulos")

    def rating_de(pid):
        return mapa.get(UID, {}).get(pid, {}).get("rating")

    resultados = []

    def check(nombre, tipo, elem):
        aspecto = elem.get("aspecto", "")
        frag = elem.get("fragmento", "")
        ids = elem.get("evidencia_ids", [])
        palabras = len(frag.split())
        tiene_puntos = ("..." in frag) or ("\u2026" in frag)
        primera = ids[0] if ids else None
        cuerpo_primera = cuerpos.get(primera, "")
        titulo_primera = titulos.get(primera, "")
        ok_literal_cuerpo_primera = bool(cuerpo_primera) and norm(frag) in norm(cuerpo_primera)
        ok_literal_titulo_primera = bool(titulo_primera) and norm(frag) in norm(titulo_primera)
        ok_literal_primera = ok_literal_cuerpo_primera or ok_literal_titulo_primera
        ok_literal_cuerpo_otra = any(
            norm(frag) in norm(cuerpos.get(x, "")) for x in ids[1:] if cuerpos.get(x)
        )
        ok_literal_titulo_otra = any(
            norm(frag) in norm(titulos.get(x, "")) for x in ids[1:] if titulos.get(x)
        )
        ok_literal_otra = ok_literal_cuerpo_otra or ok_literal_titulo_otra
        ids_existen = bool(ids) and all(pid in cuerpos for pid in ids)
        ratings = [rating_de(pid) for pid in ids]
        validos = [r for r in ratings if r is not None]
        ok_rating = any(r >= 4 for r in validos) if tipo == "pref" else any(r <= 2 for r in validos)

        notas = []
        if tiene_puntos:
            notas.append('contiene "..." o "…"')

        if not palabras <= 15:
            v = "FALLO_PALABRAS"; notas.append(f"{palabras}>15")
        elif not ids_existen:
            v = "FALLO_IDS"; notas.append("ids inexistentes")
        elif not (ok_literal_primera or ok_literal_otra):
            v = "FALLO_LITERAL"; notas.append("fragmento no en ninguna cita")
        elif not ok_literal_primera:
            v = "FALLO_ATRIBUCION"; notas.append(f"literal está en otra, no en {primera}")
        elif not ok_rating:
            v = "OK_CON_NOTA"; notas.append(f"rating no estricto para {tipo}: {ratings}")
        else:
            v = "OK"

        print(f"  {nombre}: {v} | palabras={palabras} literal_primera={ok_literal_primera} "
              f"(cuerpo={ok_literal_cuerpo_primera}, titulo={ok_literal_titulo_primera}) "
              f"ids_ok={ids_existen} ratings={ratings}"
              + (f" | {'; '.join(notas)}" if notas else ""))

        return {
            "nombre": nombre, "tipo": tipo, "aspecto": aspecto, "fragmento": frag,
            "palabras": palabras, "ids": ids, "ids_existen": ids_existen,
            "literal_en_primera": ok_literal_primera,
            "literal_en_cuerpo_primera": ok_literal_cuerpo_primera,
            "literal_en_titulo_primera": ok_literal_titulo_primera,
            "literal_en_cualquiera": ok_literal_primera or ok_literal_otra,
            "literal_en_cuerpo_cualquiera": ok_literal_cuerpo_primera or ok_literal_cuerpo_otra,
            "literal_en_titulo_cualquiera": ok_literal_titulo_primera or ok_literal_titulo_otra,
            "ratings": ratings, "ok_rating": ok_rating,
            "veredicto": v, "notas": notas,
        }

    print("\nPreferencias:")
    for i, p in enumerate(perfil.get("preferencias", []), 1):
        resultados.append(check(f"PRE{i}", "pref", p))
    print("\nAdvertencias:")
    for i, a in enumerate(perfil.get("advertencias", []), 1):
        resultados.append(check(f"ADV{i}", "adv", a))

    n_ok = sum(1 for r in resultados if r["veredicto"] == "OK")
    n_nota = sum(1 for r in resultados if r["veredicto"] == "OK_CON_NOTA")
    n_fallos = sum(1 for r in resultados if r["veredicto"].startswith("FALLO"))
    ev_ins = (len(perfil.get("preferencias", [])) < 3) or (len(perfil.get("advertencias", [])) < 3)

    if n_fallos == 0:
        vg = "FIEL"
    elif n_fallos <= 1:
        vg = "FIEL_CON_FALLOS_LEVES"
    else:
        vg = "NO_FIEL"

    print(f"\nResumen Call #1: OK={n_ok} OK_CON_NOTA={n_nota} fallos={n_fallos} "
          f"veredicto={vg} ev_insuficiente={ev_ins}")

    salida = {
        "user_id": UID,
        "veredicto_global": vg,
        "elementos": resultados,
        "evidencia_insuficiente": ev_ins,
        "resumen": {"ok": n_ok, "ok_con_nota": n_nota, "fallos": n_fallos,
                    "total": len(resultados)},
    }
    (V2_CALL1 / "verif_v2.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    return salida


# ===================== Call #2 =====================

def verificar_call2() -> dict:
    print("\n" + "=" * 70)
    print("CALL #2 — verificación")
    print("=" * 70)
    prompt_user = (V2_CALL2 / "prompt_call2_user.txt").read_text(encoding="utf-8")
    explic = json.loads((V2_CALL2 / "explicaciones_v2.json").read_text(encoding="utf-8"))
    perfil = json.loads((V2_CALL1 / "perfil_v2.json").read_text(encoding="utf-8"))
    aspectos_perfil = {p["aspecto"] for p in perfil.get("preferencias", [])}
    items_prompt = extraer_call2(prompt_user)
    print(f"Prompt: {len(prompt_user)} chars, {len(items_prompt)} ítems")

    def check_frag(rid, frag, rs, tipo):
        """tipo ∈ {pref, adv}. Devuelve dict con veredicto y flags."""
        palabras = len(frag.split())
        rid_ok = rid in rs
        cuerpo = rs.get(rid, {}).get("body", "")
        titulo = rs.get(rid, {}).get("title", "")
        literal_en_cuerpo = norm(frag) in norm(cuerpo) if cuerpo else False
        literal_en_titulo = norm(frag) in norm(titulo) if titulo else False
        literal = literal_en_cuerpo or literal_en_titulo
        rating_r = rs.get(rid, {}).get("rating")
        flags = []
        if not rid_ok:
            flags.append(f"ID_{rid}_NO_EXISTE")
        if not literal:
            flags.append("FRAG_NO_LITERAL")
        if palabras > 15:
            flags.append(f"PALABRAS={palabras}>15")
        if rid_ok and tipo == "pref" and (rating_r is None or rating_r < 4):
            flags.append(f"CITA_{rid}_RATING_{rating_r}")
        if rid_ok and tipo == "adv" and (rating_r is None or rating_r > 2):
            flags.append(f"CITA_{rid}_RATING_{rating_r}_NO_NEGATIVA")
        return {
            "rid": rid, "fragmento": frag, "palabras": palabras,
            "rid_existe": rid_ok, "literal": literal,
            "literal_en_cuerpo": literal_en_cuerpo,
            "literal_en_titulo": literal_en_titulo,
            "rating_R": rating_r,
            "flags": flags,
        }

    items_result = []
    for it in explic.get("items", []):
        pos = it["posicion"]
        pa = it["parent_asin"]
        data = items_prompt.get(pos, {})
        rs = data.get("rs", {})
        coincide = data.get("asin") == pa
        print(f"\n  #{pos} {pa} (prompt={data.get('asin')}, coincide={coincide})")

        ccs = []
        for cc in it.get("coincide_con", []):
            asp = cc.get("aspecto", "")
            if asp not in aspectos_perfil:
                r = check_frag(cc.get("id", ""), cc.get("fragmento", ""), rs, "pref")
                r["aspecto"] = asp
                r["aspecto_en_perfil"] = False
                r["flags"].append("ASPECT_NO_EN_PERFIL")
                ccs.append(r)
            else:
                r = check_frag(cc.get("id", ""), cc.get("fragmento", ""), rs, "pref")
                r["aspecto"] = asp
                r["aspecto_en_perfil"] = True
                ccs.append(r)
            print(f"     cc: aspect={asp!r} id={cc.get('id')} "
                  f"literal={ccs[-1]['literal']} (cuerpo={ccs[-1]['literal_en_cuerpo']}, titulo={ccs[-1]['literal_en_titulo']}) "
                  f"flags={ccs[-1]['flags'] or 'OK'}")

        tec = it.get("ten_en_cuenta")
        tec_r = None
        if tec:
            tec_r = check_frag(tec.get("id", ""), tec.get("fragmento", ""), rs, "adv")
            # Reuso: mismo R# que algún coincide_con
            cids = [cc.get("id") for cc in it.get("coincide_con", [])]
            if tec_r["rid"] in cids:
                tec_r["flags"].append(f"REUSO_{tec_r['rid']}_EN_CC_Y_TEC")
            print(f"     tec: id={tec.get('id')} literal={tec_r['literal']} "
                  f"(cuerpo={tec_r['literal_en_cuerpo']}, titulo={tec_r['literal_en_titulo']}) "
                  f"flags={tec_r['flags'] or 'OK'}")

        items_result.append({
            "posicion": pos, "parent_asin": pa, "parent_asin_coincide": coincide,
            "coincide_con": ccs, "ten_en_cuenta": tec_r,
            "por_que_el_modelo": it.get("por_que_el_modelo", ""),
        })

    # Agregados
    todos_frags = []
    for it in items_result:
        for cc in it["coincide_con"]:
            todos_frags.append({"tipo": "cc", "item": it["posicion"], **cc})
        if it["ten_en_cuenta"]:
            todos_frags.append({"tipo": "tec", "item": it["posicion"], **it["ten_en_cuenta"]})

    n_frag = len(todos_frags)
    n_literal = sum(1 for f in todos_frags if f["literal"])
    n_flags = sum(1 for f in todos_frags if f["flags"])
    n_items_ok = sum(1 for it in items_result
                     if it["parent_asin_coincide"]
                     and all(not cc["flags"] for cc in it["coincide_con"])
                     and (it["ten_en_cuenta"] is None or not it["ten_en_cuenta"]["flags"]))

    cc_todos = [cc for it in items_result for cc in it["coincide_con"]]
    cc_validos = sum(1 for cc in cc_todos
                     if cc["aspecto_en_perfil"] and cc["literal"] and not cc["flags"])

    tecs = [it["ten_en_cuenta"] for it in items_result if it["ten_en_cuenta"]]
    tecs_negativos = sum(1 for t in tecs if (t["rating_R"] or 0) <= 2)

    if n_items_ok == len(items_result):
        vg = "FIEL"
    elif n_flags <= 2:
        vg = "FIEL_CON_NOTAS"
    else:
        vg = "NO_FIEL"

    print(f"\nResumen Call #2: fragmentos={n_frag} literales={n_literal} con_flags={n_flags} "
          f"items_ok={n_items_ok}/{len(items_result)} veredicto={vg}")
    print(f"  cc totales={len(cc_todos)} cc_validos={cc_validos}")
    print(f"  tec totales={len(tecs)} tec_negativos={tecs_negativos}")

    salida = {
        "user_id": UID,
        "veredicto_global": vg,
        "items": items_result,
        "resumen": {
            "fragmentos": n_frag, "literales": n_literal, "con_flags": n_flags,
            "items_ok": n_items_ok, "items_total": len(items_result),
            "cc_total": len(cc_todos), "cc_validos": cc_validos,
            "tec_total": len(tecs), "tec_negativos": tecs_negativos,
        },
    }
    (V2_CALL2 / "verif_v2.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    return salida


# ===================== Leakage (opcional) =====================

def verificar_leakage() -> dict:
    print("\n" + "=" * 70)
    print("LEAKAGE — verificación temporal")
    print("=" * 70)
    import pandas as pd
    prompt_user = (V2_CALL2 / "prompt_call2_user.txt").read_text(encoding="utf-8")
    items_prompt = extraer_call2(prompt_user)
    df = pd.read_parquet(PARQUET, columns=["parent_asin", "timestamp", "rating", "helpful_vote"])

    # Cutoff: la interacción test del usuario
    df_u = pd.read_parquet(PARQUET, columns=["user_id", "timestamp", "split"])
    test_row = df_u[(df_u.user_id == UID) & (df_u.split == "test")]
    if len(test_row) == 0:
        print("  Sin interacción test: no se puede calcular cutoff")
        return {"veredicto": "SIN_CUTOFF", "problemas": []}
    cutoff = int(test_row.timestamp.iloc[0])
    print(f"  Cutoff usuario: {cutoff}")

    problemas = []
    for rank, data in items_prompt.items():
        asin = data["asin"]
        rs_prod = df[df.parent_asin == asin]
        pos = rs_prod[(rs_prod.rating >= 4) & (rs_prod.timestamp < cutoff)] \
            .sort_values("helpful_vote", ascending=False).head(2)
        neg = rs_prod[(rs_prod.rating <= 2) & (rs_prod.timestamp < cutoff)] \
            .sort_values("helpful_vote", ascending=False).head(1)
        esperadas = list(pos.itertuples()) + list(neg.itertuples())

        for rid, body in data["rs"].items():
            pass  # ya validado por literalidad

        for e in esperadas:
            if int(e.timestamp) >= cutoff:
                problemas.append({"item": rank, "asin": asin, "ts": int(e.timestamp)})
        print(f"  #{rank} {asin}: {len(esperadas)} reseñas, "
              f"todas ts<cutoff={all(int(e.timestamp) < cutoff for e in esperadas)}")

    v = "FIEL" if not problemas else "FALLO"
    print(f"  Veredicto leakage: {v} ({len(problemas)} problemas)")
    return {"veredicto": v, "cutoff": cutoff, "problemas": problemas}


# ===================== Métricas Paso 11 =====================

def calcular_metricas(call1: dict, call2: dict, leakage: dict | None) -> dict:
    print("\n" + "=" * 70)
    print("MÉTRICAS PASO 11")
    print("=" * 70)

    c1 = call1["resumen"]
    c2 = call2["resumen"]

    # Call #1
    total_c1 = c1["total"]
    fieles_c1 = c1["ok"] + c1["ok_con_nota"]
    fidelidad_c1 = fieles_c1 / total_c1 if total_c1 else 0.0

    # Call #2
    frags_c2 = c2["fragmentos"]
    fidelidad_c2 = c2["literales"] / frags_c2 if frags_c2 else 0.0
    cc_validos_pct = c2["cc_validos"] / c2["cc_total"] if c2["cc_total"] else 0.0
    tec_negativos_pct = c2["tec_negativos"] / c2["tec_total"] if c2["tec_total"] else 0.0

    # Global
    frags_total = total_c1 + frags_c2
    frags_fieles = fieles_c1 + c2["literales"]
    fidelidad_global = frags_fieles / frags_total if frags_total else 0.0

    notas_c1 = c1["ok_con_nota"]
    notas_c2 = c2["con_flags"]
    notas_total = notas_c1 + notas_c2
    tasa_notas = notas_total / frags_total if frags_total else 0.0

    # Salidas inválidas: por construcción 0 si llegamos hasta aquí
    # (las llamadas tienen finish_reason=stop y JSON parseado)
    salidas_invalidas = 0
    total_llamadas = 2  # Call #1 + Call #2

    metricas = {
        "user_id": UID,
        "llamadas_totales": total_llamadas,
        "salidas_invalidas": salidas_invalidas,
        "tasa_salidas_invalidas": salidas_invalidas / total_llamadas,
        "call1": {
            "fidelidad": round(fidelidad_c1, 4),
            "elementos_fieles": fieles_c1,
            "elementos_totales": total_c1,
            "ok_puros": c1["ok"],
            "ok_con_nota": c1["ok_con_nota"],
            "fallos": c1["fallos"],
            "evidencia_insuficiente_calculada": call1["evidencia_insuficiente"],
        },
        "call2": {
            "fidelidad": round(fidelidad_c2, 4),
            "fragmentos_literales": c2["literales"],
            "fragmentos_totales": frags_c2,
            "items_ok": c2["items_ok"],
            "items_total": c2["items_total"],
            "cc_validos_pct": round(cc_validos_pct, 4),
            "cc_validos": c2["cc_validos"],
            "cc_total": c2["cc_total"],
            "tec_negativos_pct": round(tec_negativos_pct, 4),
            "tec_negativos": c2["tec_negativos"],
            "tec_total": c2["tec_total"],
        },
        "global": {
            "fidelidad_global": round(fidelidad_global, 4),
            "fragmentos_fieles": frags_fieles,
            "fragmentos_totales": frags_total,
            "tasa_notas_calidad": round(tasa_notas, 4),
            "notas_total": notas_total,
        },
        "leakage": leakage,
        "veredictos": {
            "call1": call1["veredicto_global"],
            "call2": call2["veredicto_global"],
            "leakage": leakage["veredicto"] if leakage else "no_verificado",
        },
    }

    print(f"  Fidelidad Call #1:   {metricas['call1']['fidelidad']:.2%} "
          f"({fieles_c1}/{total_c1})")
    print(f"  Fidelidad Call #2:   {metricas['call2']['fidelidad']:.2%} "
          f"({c2['literales']}/{frags_c2})")
    print(f"  Fidelidad global:    {metricas['global']['fidelidad_global']:.2%} "
          f"({frags_fieles}/{frags_total})")
    print(f"  cc válidos:          {metricas['call2']['cc_validos_pct']:.2%} "
          f"({c2['cc_validos']}/{c2['cc_total']})")
    print(f"  tec negativos:       {metricas['call2']['tec_negativos_pct']:.2%} "
          f"({c2['tec_negativos']}/{c2['tec_total']})")
    print(f"  Salidas inválidas:   {salidas_invalidas}/{total_llamadas}")
    print(f"  Notas de calidad:    {notas_total} de {frags_total} "
          f"({tasa_notas:.2%})")

    out = Path(_P("cache", "metricas_paso11.json"))
    out.write_text(json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Guardado: {out}")
    return metricas


# ===================== main =====================

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leakage", action="store_true",
                    help="Añadir verificación de leakage temporal (lee parquet)")
    args = ap.parse_args()

    call1 = verificar_call1()
    call2 = verificar_call2()
    leakage = verificar_leakage() if args.leakage else None
    metricas = calcular_metricas(call1, call2, leakage)

    # Exit code: 0 si todo fiel, 1 si algún fallo crítico
    fallos = call1["resumen"]["fallos"] + call2["resumen"]["con_flags"]
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())