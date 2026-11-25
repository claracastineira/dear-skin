"""Ingesta (RAG): guarda productos e ingredientes en ChromaDB.

Dos colecciones:
  - productos:    un Document por producto, con metadatos para filtrar (zona, precio, origen...)
  - ingredientes: los .md de data/ingredientes troceados en fragmentos
                  + una ficha por ingrediente del dataset abierto (irritación, embarazo, mezclas)

Se ejecuta una vez, y otra cada vez que cambien los datos:
    python -m app.ingesta
"""

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import ingredientes
from app.catalogo import cargar_productos, texto_para_embedding
from app.config import (CARPETA_CHROMA, CARPETA_INGREDIENTES, COLECCION_INGREDIENTES,
                        COLECCION_PRODUCTOS, crear_embeddings)
from app.resenas import inicializar
from app.usuarios import conectar as crear_tablas_usuarios


def documentos_productos() -> list[Document]:
    return [
        Document(
            page_content=texto_para_embedding(p),
            # ChromaDB solo admite metadatos escalares: las listas se filtran en Python
            metadata={"id": p["id"], "zona": p["zona"], "paso": p["paso"], "origen": p["origen"],
                      "precio": float(p["precio"] or 0), "marca": p["marca"]},
        )
        for p in cargar_productos()
    ]


def documentos_ingredientes() -> list[Document]:
    documentos = [
        Document(page_content=f.read_text(encoding="utf-8"), metadata={"fuente": f.name})
        for f in sorted(CARPETA_INGREDIENTES.glob("*.md"))
    ]
    # Cortamos preferentemente por apartados (##) y luego por párrafos
    troceador = RecursiveCharacterTextSplitter(
        chunk_size=700, chunk_overlap=80, separators=["\n## ", "\n\n", "\n", ". ", " "]
    )
    fichas = [Document(page_content=ingredientes.ficha_texto(i), metadata={"fuente": f"ingrediente:{i}"})
              for i in ingredientes.todos_los_ids()]
    return troceador.split_documents(documentos) + fichas + documentos_compatibilidad()


def documentos_compatibilidad() -> list[Document]:
    """Una ficha por familia de activos de la matriz de compatibilidad, con todas sus relaciones."""
    m = ingredientes.matriz()
    docs = []
    for clave, f in m["familias"].items():
        lineas = [f"Compatibilidad de {f['nombre']}. Momento: {f['momento']}. Irritación: {f['irritacion']}.",
                  f"Ideal para piel: {', '.join(f['ideal']) or '-'}. Con cuidado en piel: {', '.join(f['cuidado']) or '-'}.",
                  f.get("nota", "")]
        for r in m["relaciones"]:
            if clave in (r["a"], r["b"]):
                otra = m["familias"][r["b"] if r["a"] == clave else r["a"]]["nombre"]
                lineas.append(f"- Con {otra}: {m['tipos'][r['tipo']]}. {r['porque']} {r['como']}")
        docs.append(Document(page_content="\n".join(lineas), metadata={"fuente": f"compatibilidad:{clave}"}))
    return docs


def indexar(embeddings=None) -> tuple[int, int]:
    embeddings = embeddings or crear_embeddings()
    totales = []
    for coleccion, docs, clave in (
        (COLECCION_PRODUCTOS, documentos_productos(), lambda i, d: d.metadata["id"]),
        (COLECCION_INGREDIENTES, documentos_ingredientes(),
         lambda i, d: f"{d.metadata['fuente']}-{i}"),
    ):
        base = Chroma(collection_name=coleccion, embedding_function=embeddings,
                      persist_directory=str(CARPETA_CHROMA))
        # Identificadores fijos: al repetir la ingesta se sobrescriben, no se duplican
        base.add_documents(docs, ids=[clave(i, d) for i, d in enumerate(docs)])
        totales.append(len(docs))
    return tuple(totales)


if __name__ == "__main__":
    n_productos, n_fragmentos = indexar()
    inicializar()            # crea dear_skin.db con las reseñas de ejemplo si no existe
    crear_tablas_usuarios().close()
    print(f"Guardados {n_productos} productos y {n_fragmentos} fragmentos/fichas de ingredientes "
          f"en {CARPETA_CHROMA}")
