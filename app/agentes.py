"""Agentes especialistas.

Agente = modelo + instrucciones (system prompt) + herramientas.
create_agent monta el bucle: pensar -> usar herramienta -> leer resultado -> responder.

Las herramientas llegan del servidor MCP (app/servidor_mcp.py). El personal shopper
(rutinas) y el detector de hype no son agentes LLM sino nodos deterministas del grafo
que llaman directamente al optimizador (app/rutina.py) y a app/hype.py.
"""

import sys
from contextlib import asynccontextmanager

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from app.config import RAIZ


@asynccontextmanager
async def herramientas_mcp():
    """Arranca el servidor MCP UNA vez y mantiene la sesión abierta mientras dure el bloque.

    Así el modelo de embeddings se carga una sola vez y no en cada llamada.
    """
    cliente = MultiServerMCPClient(
        {
            "dear-skin": {
                "transport": "stdio",
                "command": sys.executable,  # el mismo Python que ejecuta este programa
                "args": ["-m", "app.servidor_mcp"],
                "cwd": str(RAIZ),
            }
        }
    )
    async with cliente.session("dear-skin") as sesion:
        yield await load_mcp_tools(sesion)


PROMPT_ASESOR = """Eres el asesor de productos de Dear Skin, una web de skincare coreano (y de farmacia)
para cara, cuerpo y pelo. Busca SIEMPRE con la herramienta buscar_productos y traduce lo que pide
el usuario a filtros: tipo de piel/pelo -> apto_para; "granitos" -> objetivos ["acne"];
"que no obstruya poros" -> caracteristicas ["no_comedogenico"]; "que dé brillo" -> objetivos
["brillo"] (pelo) o caracteristicas ["aporta_brillo"]; "manchas" -> objetivos ["manchas"];
rango de precio -> precio_min/precio_max; alergias -> evitar_ingredientes (y si la piel es
sensible, añade "sin_perfume"). Si no sale nada, repite relajando UN filtro y dilo.
Devuelve SIEMPRE 3 opciones (o 2 si no hay más) que cumplan lo que pide, de la que mejor encaja a la
que menos, intentando variar precio o estilo (por ejemplo una más económica). Para cada una copia tal
cual su [ref:id], marca, nombre, precio, ingredientes clave y tiendas, y explica por qué encaja.
No inventes productos."""

PROMPT_EXPERTO = """Eres el experto en ingredientes. Si te preguntan si se pueden juntar o mezclar
productos o activos, o cómo combinarlos, llama ANTES a comprobar_compatibilidad con todos ellos y
basa tu respuesta en su veredicto (no lo contradigas). Busca SIEMPRE con explicar_ingrediente y explica,
con palabras sencillas y en 1-3 frases por ingrediente, qué es (p. ej. "el retinol es un derivado de
la vitamina A"), para qué sirve, cómo introducirlo y sus precauciones (sol, embarazo, mezclas,
alergias). Responde solo con lo que digan los documentos y cita el fichero de la fuente."""

PROMPT_ANALISTA = """Eres el analista de reseñas. Para cada producto que te pidan, llama a ver_resenas
con su id (el texto de [ref:id]) y, si lo sabes, el tipo de piel del usuario. Resume en una o dos
frases por producto: nota media, si funciona a largo plazo (8+ semanas), % de reacciones y cómo le
fue a gente con su tipo de piel. Avisa si son pocas reseñas o si son reseñas de ejemplo."""


def crear_especialistas(modelo, herramientas: list) -> dict:
    """Devuelve un diccionario {nombre: agente}."""
    por_nombre = {h.name: h for h in herramientas}
    return {
        "asesor_productos": create_agent(
            modelo, tools=[por_nombre["buscar_productos"]], system_prompt=PROMPT_ASESOR,
            name="asesor_productos",
        ),
        "experto_ingredientes": create_agent(
            modelo, tools=[por_nombre["explicar_ingrediente"], por_nombre["comprobar_compatibilidad"]],
            system_prompt=PROMPT_EXPERTO,
            name="experto_ingredientes",
        ),
        "analista_resenas": create_agent(
            modelo, tools=[por_nombre["ver_resenas"]], system_prompt=PROMPT_ANALISTA,
            name="analista_resenas",
        ),
    }
