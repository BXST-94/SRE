# Recomendador explicable en Amazon Electronics

Prototipo, no es un sistema en producción. Se usa un modelo SASRec (Top-5 recomendaciones por usuario). Se usa un mecanismo de atribución contrafactual para entender las reseñas históricas que contribuyeron a cada recomendación. El razonamiento proviene del modelo, el LLM sólo traduce eso en palabras. Se verifica automáticamente (sin usar LLM) que las citas en efecto existan en las reseñas.

- Falta: la atribución responde a qué usó el modelo para hacer la recomendación. Pero no es lo mismo que la causa real del comportamiento de compra.

## Contenido

| Carpeta | Contenido |
|---|---|
| `actividad/` | notebook de la actividad (pandas, matplotlib, bokeh). datos iniciales, base de sqlite, sql, script para generar la base, dataset final |
| `app/` | app (flask) del recomendador |
| `src/` | cliente de LLM. perfil de usuario. verificador |
| `data/`, `cache/` | data pre-calculada para usuarios de demo |

## Actividad (Pandas, Matplotlib, Bokeh)

[![Abrir en Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/BXST-94/SRE/blob/main/actividad/actividad_pandas.ipynb)

- Dataset 1 (csv) - `actividad/datos_iniciales/items_muestra.csv` (con metadatos de productos)
- Dataset 2 (base de datos) - `actividad/amazon_electronics.sqlite`. Contiene reseñas. Generado por `actividad/crear_bd.py`. esquema en `actividad/sql/schema.sql`. ejemplos de consultas en `actividad/sql/consultas_ejemplo.sql`
- Notebook - `actividad/actividad_pandas.ipynb` (funciona en JupyterLab, y en Google Colab)
- Final dataset `actividad/dataset_final/`
- Dependencias `actividad/requirements.txt`

Dataset: 500 usuarios reproductibles (semilla 42) del 5-core subconjunto de Amazon reviews 2023 (categoria Electronics) McAuley Lab.

Amazon Reviews 2023 (McAuley Lab, UCSD). Publicado para investigar. No asignan licencia ni condiciones de uso. Uso ético y dentro de lo que marca la ley. Reseñas y metadatos de los autores y de Amazon. La muestra de activity/ y datos de demostración de data/ y cache/ son para uso académico y no comercial. Al utilizar, favor citar la obra https://amazon-reviews-2023.github.io/. Si eres titular de algo y quieres que se quite, abre un issue en este repo.

## Web recommender (Flask)

Local

    pip install -r requirements.txt
    python app/app.py

Abrir http://127.0.0.1:5000, Necesitas una key de openrouter que pegas en pestaña de carga para análisis live de un usuario.

## Desplegar en Render

`render.yaml`, que describe servicio. Solo un proceso de gunicorn, porque los análisis que se están haciendo se mantienen en memoria. El plan gratis se duerme a los pocos minutos que no hay visitantes. Por eso la carga inicial puede llevar su tiempo.

### Tutorial de uso (Chatbot)

Puedes acceder a la aplicación desplegada en Render en la siguiente URL: **https://recomendador-explicable.onrender.com** *(asegúrate de que coincida con la URL que te asignó Render, a veces incluye un sufijo aleatorio)*.

Para usar el Chatbot:
1. **Agregar la API Key:** En la barra lateral izquierda, busca la sección **⚙️ API key** (abajo a la izquierda). Pega tu clave de OpenRouter (empieza por `sk-or-`).
2. **Seleccionar un usuario:** En esa misma barra lateral, elige un usuario en el menú desplegable. Esto cargará su historial de compras para personalizar las respuestas.
3. **Escribir en el chat:** Ve a la caja de texto en la parte inferior central, escribe lo que buscas (ej. *"Quiero un router WiFi 6 para casa de 100 m2, menos de 150 USD"*) y presiona **Enter**. También puedes hacer clic en las categorías de la barra lateral derecha para iniciar una búsqueda automática.

## CLAVE DE API.

Cada visitante pega su clave de OpenRouter. Se pasa a un servidor solo para hacer ese análisis. No se guarda en disco. Ni se comparte con otros visitantes. Utiliza clave desechable o limitada de gasto. Revoca la clave una vez hagas la prueba. No establezcas DEMO_KEY en un sitio público, todos los visitantes estarían gastando ese saldo. LIMITE_DIARIO (default 100) Limita las llamadas al dia.

Un análisis te cuesta alrededor de 0.003 USD y te tarda aproximadamente 1min. (ya que hace 2 llamadas al modelo)