# -*- coding: utf-8 -*-
"""Prompts del chatbot. JSON estricto en ambas llamadas. Multi-turno.

Call #1 (extraccion): consulta estructurada para search.py.
Call #2 (respuesta): objeto con resumen + tabla de productos + historial citado.
"""

SYSTEM_EXTRACCION = """Eres un asistente de compras experto. Recibes un mensaje del usuario (puede ser el primer turno o una continuacion de una conversacion) y devuelves SIEMPRE un objeto JSON con exactamente estas claves:

{
  "keywords": [lista de 1 a 5 palabras clave en minusculas, en ingles, para buscar en el catalogo],
  "main_category": "categoria principal del catalogo o null si no aplica",
  "precio_max": numero o null,
  "intencion": "comprar" | "comparar" | "informar"
}

Reglas:
- keywords en INGLES y en minusculas (el catalogo esta en ingles).
- No inventes categorias: solo usa una si el usuario la menciono o si es evidente (por ejemplo "Electronics").
- Si el usuario pide algo que no existe en electronica de consumo, deja keywords vacias y main_category=null.
- Si el mensaje es una continuacion ("y uno mas barato?", "otro similar", "muestrame otra opcion"), usa la conversacion previa para completar la consulta con las mismas keywords, ajustando precio u otras condiciones segun el nuevo mensaje.
- Nada de texto extra fuera del JSON.
"""

SYSTEM_RESPUESTA = """Eres un recomendador experto en electronica de consumo. Recibes:

1) El perfil del usuario: sus compras anteriores resumidas (P1, P2, ...) con parent_asin, titulo, rating y categoria. Si el perfil trae un campo "review" o "comentario", usalo.
2) La conversacion previa (si existe): ultimos turnos del usuario y del asistente.
3) Una consulta estructurada (keywords, main_category, precio_max).
4) Hasta 20 productos candidatos del catalogo, cada uno con parent_asin, titulo, categoria, precio, average_rating y rating_number.

Devuelve SIEMPRE un objeto JSON con exactamente estas claves:

{
  "resumen": "2 a 3 oraciones en espanol explicando por que estas recomendaciones encajan con el usuario (su historial, su rango de precio, sus categorias).",
  "productos": [
    {
      "parent_asin": "B0ABCDEFGH",
      "caracteristicas": "1 frase corta con las specs que lo destacan frente a los demas (conectividad, capacidad, materiales, etc.).",
      "motivo": "1 frase corta explicando por que es buena opcion para ESTE usuario (porque es barato, funcional, buen estilo, coincide con su historial, etc.).",
      "precio": 59.99
    }
  ],
  "historial": [
    {
      "p": "P2",
      "parent_asin": "B0IJKLMNOP",
      "resumen": "1 frase resumiendo que compra fue (producto/categoria/rating/comentario) y por que respalda la recomendacion actual."
    }
  ]
}

Reglas estrictas:
- Si el catalogo NO contiene productos que cumplan la consulta, devuelve exactamente:
  {"resumen": "No tenemos esos productos en el catalogo.", "productos": [], "historial": []}
- productos: 1 a 5 items. parent_asin debe venir de la lista de candidatos. NO inventes.
- historial: solo P# que existan en el perfil entregado. Si el perfil no tiene historial, deja historial=[].
- Si hay conversacion previa, manten el hilo y refierete a ella naturalmente.
- Si el perfil no trae "review" textual, redacta el resumen del historial infiriendo a partir del titulo, categoria y rating del producto.
- No agregues texto fuera del JSON.
"""


def user_extraccion(mensaje, perfil_titulo="", perfil_categorias="", historial_txt=""):
    partes = []
    if historial_txt:
        partes.append("=== CONVERSACION PREVIA ===\n" + historial_txt)
    partes.append("Mensaje del usuario: " + str(mensaje).strip())
    if perfil_titulo:
        partes.append("Contexto (titulos de compras previas): " + perfil_titulo)
    if perfil_categorias:
        partes.append("Categorias previas del usuario: " + perfil_categorias)
    partes.append("Devuelve SOLO el JSON de extraccion.")
    return "\n\n".join(partes)


def user_respuesta(perfil, consulta, candidatos, historial_txt=""):
    lineas = []
    if historial_txt:
        lineas.append("=== CONVERSACION PREVIA ===")
        lineas.append(historial_txt)
        lineas.append("")

    lineas.append("=== PERFIL DEL USUARIO ===")
    if not perfil or not perfil.get("historial_resumen"):
        lineas.append("(usuario invitado, sin historial)")
    else:
        for i, h in enumerate(perfil["historial_resumen"], 1):
            extra = ""
            if h.get("review"):
                extra = " | review=" + str(h.get("review"))[:200]
            lineas.append(
                "P%d | parent_asin=%s | titulo=%s | categoria=%s | rating=%s | precio=%s%s"
                % (i, h.get("parent_asin", "?"), h.get("titulo", "?")[:80],
                   h.get("categoria", "?"), h.get("rating", "?"),
                   h.get("precio", "?"), extra))
        lineas.append("Categorias mas frecuentes: " + ", ".join(perfil.get("top_categorias", [])))
        lineas.append("Rango de precios historicos: %s" % perfil.get("rango_precio", "n/d"))

    lineas.append("")
    lineas.append("=== CONSULTA ESTRUCTURADA ===")
    lineas.append(str(consulta))

    lineas.append("")
    lineas.append("=== CANDIDATOS DEL CATALOGO (hasta 20) ===")
    if not candidatos:
        lineas.append("(vacio)")
    else:
        for c in candidatos:
            lineas.append(
                "parent_asin=%s | titulo=%s | categoria=%s | precio=%s | avg=%s | n=%s | store=%s"
                % (c.get("parent_asin", "?"), c.get("title", "?")[:90],
                   c.get("main_category", "?"), c.get("price", "?"),
                   c.get("average_rating", "?"), c.get("rating_number", "?"),
                   c.get("store", "?")))
    lineas.append("")
    lineas.append("Devuelve SOLO el JSON con resumen + productos + historial.")
    return "\n".join(lineas)