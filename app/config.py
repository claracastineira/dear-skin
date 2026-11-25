"""Configuración común: rutas, modelo de lenguaje y modelo de embeddings."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Lee las variables del fichero .env (por ejemplo, GROQ_API_KEY)
load_dotenv()

RAIZ = Path(__file__).parent.parent
CARPETA_DATOS = RAIZ / "data"
CATALOGO = CARPETA_DATOS / "productos.csv"               # catálogo curado (editable en Excel)
CARPETA_IMPORTADOS = CARPETA_DATOS / "importados"        # productos de scripts/importar_*.py
TIENDAS = CARPETA_DATOS / "tiendas.json"                 # plantillas de enlaces de compra
CARPETA_INGREDIENTES = CARPETA_DATOS / "ingredientes"   # documentos .md para el RAG
DATASET_INGREDIENTES = CARPETA_DATOS / "externos" / "skincare-ingredients-dataset"
INGREDIENTES_EXTRA = CARPETA_DATOS / "ingredientes_extra.json"
COMPATIBILIDAD = CARPETA_DATOS / "compatibilidad.json"   # matriz de compatibilidad de activos
RESENAS_EJEMPLO = CARPETA_DATOS / "resenas_ejemplo.json"
CARPETA_CHROMA = RAIZ / "chroma_db"                      # base vectorial en disco
BASE_DATOS = RAIZ / "dear_skin.db"                             # SQLite: usuarios, armario, diario, reseñas
BASE_RESENAS = BASE_DATOS

COLECCION_PRODUCTOS = "productos"
COLECCION_INGREDIENTES = "ingredientes"

# Modelo de embeddings multilingüe que se ejecuta en tu ordenador (gratis, sin clave)
MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def crear_modelo():
    """Modelo de lenguaje (LLM). Por defecto, GPT-OSS 120B en el plan gratuito de Groq."""
    from langchain.chat_models import init_chat_model

    return init_chat_model(os.getenv("MODELO", "groq:openai/gpt-oss-120b"), temperature=0.2)


def crear_embeddings():
    """Embeddings locales con fastembed, adaptados a la interfaz de LangChain."""
    from langchain_core.embeddings import Embeddings

    class EmbeddingsLocales(Embeddings):
        def __init__(self):
            from fastembed import TextEmbedding

            # La primera vez descarga el modelo (unos 220 MB) y lo guarda en caché
            self.modelo = TextEmbedding(MODELO_EMBEDDINGS)

        def embed_documents(self, textos: list[str]) -> list[list[float]]:
            return [vector.tolist() for vector in self.modelo.embed(textos)]

        def embed_query(self, texto: str) -> list[float]:
            return self.embed_documents([texto])[0]

    return EmbeddingsLocales()
