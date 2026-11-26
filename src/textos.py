#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
textos.py — Utilidades de limpieza y recorte de texto.

Funciones:
- limpiar_texto: html.unescape; <br>, <br/>, <br /> a espacio; quita otras etiquetas HTML y todo [[...]]; colapsa espacios.
- recortar_texto(t, max_chars=500): si es más largo, corta en el último espacio antes del límite y agrega "…".
- recortar_titulo(t, max_chars=120): recorta título a max_chars.
"""

import html
import re


def limpiar_texto(text: str) -> str:
    """Limpia entidades HTML y normaliza espacios."""
    if not text:
        return ""
    # HTML entities
    text = html.unescape(text)
    # HTML tags: <br>, <br/>, <br /> -> espacio
    text = re.sub(r"<br\s*/?>", " ", text)
    # Remove other HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove [[...]] patterns
    text = re.sub(r"\[\[.*?\]\]", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def recortar_texto(t: str, max_chars: int = 500) -> str:
    """Recorta el texto a max_chars, cortando en el último espacio y agregando '…'."""
    if not t or len(t) <= max_chars:
        return t
    # Buscar el último espacio antes del límite
    cutoff = t[:max_chars]
    last_space = cutoff.rfind(' ')
    if last_space > max_chars * 0.8:  # Si hay un espacio razonablemente cerca
        return cutoff[:last_space] + "…"
    else:
        # No hay espacio conveniente, cortar duro y agregar …
        return cutoff + "…"


def recortar_titulo(t: str, max_chars: int = 120) -> str:
    """Recorta título a max_chars."""
    if not t or len(t) <= max_chars:
        return t
    cutoff = t[:max_chars]
    last_space = cutoff.rfind(' ')
    if last_space > max_chars * 0.8:
        return cutoff[:last_space] + "…"
    return cutoff + "…"


if __name__ == "__main__":
    # Tests básicos
    test = "Hola <br /> mundo <br/> esto <br> es una prueba <b>HTML</b> [[ref]]"
    print("Original:", repr(test))
    limpio = limpiar_texto(test)
    print("Limpio:", repr(limpio))
    
    largo = "a " * 300
    print("Recortado:", recortar_texto(largo, 500))
    print("Termina en …:", recortar_texto(largo, 500).endswith("…"))
    
    titulo_largo = "Este es un título muy largo que debería ser recortado correctamente"
    print("Título:", recortar_titulo(titulo_largo, 30))