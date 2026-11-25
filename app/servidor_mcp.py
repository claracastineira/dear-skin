"""Servidor MCP hecho con FastMCP: ofrece las capacidades de Dear Skin como herramientas.

Herramientas:
  - buscar_productos     RAG sobre el catálogo + filtros (zona, piel, objetivos, precio...)
  - explicar_ingrediente RAG sobre la guía de ingredientes y el dataset abierto
  - ver_resenas          estadísticas de reseñas de la comunidad (SQLite)
  - generar_rutina       el optimizador de rutinas (personal shopper)
  - merece_la_pena       análisis "worth the hype" de un producto viral
  - comprobar_compatibilidad  matriz de compatibilidad: ¿se pueden juntar estos activos/productos?

Lo puede usar cualquier cliente MCP: nuestros agentes, Claude Code, Claude Desktop...
Normalmente lo arranca el cliente; para lanzarlo a mano:
    python -m app.servidor_mcp
"""

import json

from fastmcp import FastMCP
from langchain_chroma import Chroma

from app import catalogo, compatibilidad, hype, resenas, rutina, usuarios
from app.config import CARPETA_CHROMA, COLECCION_INGREDIENTES, COLECCION_PRODUCTOS, crear_embeddings

servidor = FastMCP("dear-skin")

_embeddings = crear_embeddings()
base_productos = Chroma(collection_name=COLECCION_PRODUCTOS, embedding_function=_embeddings,
                        persist_directory=str(CARPETA_CHROMA))
base_ingredientes = Chroma(collection_name=COLECCION_INGREDIENTES, embedding_function=_embeddings,
                           persist_directory=str(CARPETA_CHROMA))
resenas.inicializar()


@servidor.tool
def buscar_productos(
    consulta: str,
    zona: str = "",
    apto_para: list[str] | None = None,
    objetivos: list[str] | None = None,
    caracteristicas: list[str] | None = None,
    precio_min: float = 0,
    precio_max: float = 0,
    evitar_ingredientes: list[str] | None = None,
    solo_coreano: bool = False,
    k: int = 5,
) -> str:
    """Busca productos concretos del catálogo (sobre todo K-beauty) que encajen con lo que pide el usuario.

    consulta: qué busca, en lenguaje natural (p. ej. "sérum para manchas que no pique").
    zona: "cara", "cuerpo" o "pelo" (vacío = cualquiera).
    apto_para: tipos de piel o pelo que el producto DEBE admitir, p. ej. ["mixta", "sensible"].
      piel -> grasa, seca, mixta, normal, sensible, acneica, madura, atopica
      pelo -> graso, seco, dañado, teñido, rizado, fino, caspa, cuero_sensible
    objetivos: lo que debe conseguir, p. ej. ["acne", "luminosidad"].
      cara -> acne, poros, grasa, luminosidad, manchas, hidratacion, calmar, rojeces, barrera,
              antiedad, textura, ojeras
      cuerpo -> hidratacion, piel_aspera, granitos_cuerpo, calmar, luminosidad, barrera
      pelo -> brillo, reparar, encrespamiento, caspa, cuero_graso, caida, volumen, hidratacion_pelo
    caracteristicas: no_comedogenico, sin_perfume, vegano, aporta_brillo, matificante,
      textura_ligera, textura_rica.
    precio_min / precio_max: rango de precio en euros (0 = sin límite).
    evitar_ingredientes: ingredientes a los que es alérgico o no quiere, p. ej. ["perfume"].
    solo_coreano: True para mostrar solo K-beauty.
    Devuelve fichas con [ref:id], marca, precio, ingredientes clave y tiendas donde comprarlo.
    """
    filtro = catalogo.filtro_chroma(zona, precio_min, precio_max)
    candidatos = base_productos.similarity_search(consulta, k=60, filter=filtro)
    elegidos = []
    for doc in candidatos:
        p = catalogo.producto_por_id(doc.metadata["id"])
        if p and catalogo.cumple_filtros(p, zona, apto_para, objetivos, caracteristicas,
                                         precio_min, precio_max, evitar_ingredientes, solo_coreano):
            elegidos.append(p)
        if len(elegidos) >= k:
            break
    if not elegidos:
        return ("No hay productos en el catálogo que cumplan todos los filtros. "
                "Prueba a relajar alguno (precio, objetivos, características...).")
    return "\n".join(catalogo.ficha(p) for p in elegidos)


@servidor.tool
def explicar_ingrediente(consulta: str, k: int = 4) -> str:
    """Busca en la guía de ingredientes, tipos de piel, rutina coreana y clima/viajes: qué es un
    ingrediente (retinol, niacinamida, centella, PDRN...), para qué sirve, cómo usarlo, con qué
    no mezclarlo, su irritación, si es seguro en el embarazo y la evidencia que hay detrás."""
    resultados = base_ingredientes.similarity_search(consulta, k=k)
    return "\n\n".join(f"[Fuente: {d.metadata['fuente']}]\n{d.page_content}" for d in resultados)


@servidor.tool
def comprobar_compatibilidad(elementos: list[str], tipo_piel: str = "", sensible: bool = False) -> str:
    """¿Se pueden juntar? Recibe 2-6 productos o ingredientes ("retinol", "Anua niacinamide",
    "vitamina C", "Zero Pore Pad") y consulta la matriz de compatibilidad de Dear Skin: para cada uno,
    qué familia de activos es, en qué momento del día va y si encaja con el tipo de piel; para cada
    pareja, si se potencian, si es mejor en noches distintas o uno de día y otro de noche, si hacen lo
    mismo o si no se deben juntar, con el porqué y el cómo. Úsala SIEMPRE antes de recomendar mezclas."""
    return compatibilidad.texto(compatibilidad.analizar(elementos, tipo_piel, sensible))


@servidor.tool
def ver_resenas(producto_id: str, tipo_piel: str = "") -> str:
    """Resumen de las reseñas de usuarios de un producto (usa el id de [ref:id]):
    nota media, nota de quienes lo usan 8 semanas o más (largo plazo), porcentaje de
    reacciones y, si se indica tipo_piel, cómo le ha ido a gente con ese tipo de piel."""
    datos = resenas.resumen(producto_id, tipo_piel)
    if datos["total"] == 0:
        return f"El producto {producto_id} todavía no tiene reseñas."
    return json.dumps(datos, ensure_ascii=False)


@servidor.tool
def generar_rutina(
    tipo_piel: str = "normal",
    objetivos: list[str] | None = None,
    zonas: list[str] | None = None,
    sensible: bool = False,
    tipo_pelo: str = "",
    presupuesto: float | None = None,
    max_pasos: int = 4,
    evitar_ingredientes: list[str] | None = None,
    embarazo: bool = False,
    clima: str = "",
    ya_tengo: list[str] | None = None,
    usuario_id: str = "",
) -> str:
    """Genera la rutina óptima de mañana y noche (y de cuerpo y pelo si se piden) con productos
    concretos, respetando presupuesto, número máximo de pasos, irritación acumulada, conflictos
    entre activos, ingredientes a evitar y lo que el usuario ya tiene en casa.
    clima: "", "frio_seco", "calor_humedo" o "sol_intenso". usuario_id: para usar su armario
    y su skin journey (opcional). Devuelve la rutina en texto."""
    necesidades = {k: v for k, v in locals().items() if k != "usuario_id" and v not in (None, [], "")}
    resultado = rutina.optimizar(necesidades, usuarios.contexto(usuario_id))
    return rutina.resumen_texto(resultado)


@servidor.tool
def merece_la_pena(producto: str, usuario_id: str = "") -> str:
    """Analiza si un producto (por ejemplo, uno viral de TikTok) merece la pena para la persona:
    compatibilidad, si ya tiene algo equivalente, qué aporta, conflictos, evidencia y alternativas
    más baratas. usuario_id es opcional (para usar su armario y su rutina)."""
    return json.dumps(hype.analizar(producto, usuarios.contexto(usuario_id)), ensure_ascii=False)


if __name__ == "__main__":
    # stdio: el cliente habla con el servidor por la entrada y salida estándar
    servidor.run(transport="stdio", show_banner=False, log_level="WARNING")
