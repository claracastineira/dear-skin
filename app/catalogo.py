"""Catálogo de productos: carga, normalización, enlaces de compra y filtros.

Fuentes (se combinan):
  - data/productos.csv                    catálogo curado (K-beauty + farmacia/perfumería)
  - data/importados/*.json                productos importados (scripts/importar_kbeautyanswers.py)
  - data/importados/inci_openbeautyfacts.json  activos detectados en Open Beauty Facts

Es Python puro (sin LangChain) para poder probarlo sin LLM ni base vectorial.
"""

import csv
import difflib
import json
import re
import unicodedata
from functools import lru_cache
from urllib.parse import quote_plus

from app.config import CARPETA_IMPORTADOS, CATALOGO, TIENDAS

LISTAS = ("apto_para", "objetivos", "caracteristicas", "activos", "tiendas")

OBJETIVOS = {
    "cara": ["acne", "poros", "grasa", "luminosidad", "manchas", "hidratacion", "calmar", "rojeces",
             "barrera", "antiedad", "textura", "ojeras"],
    "cuerpo": ["hidratacion", "piel_aspera", "granitos_cuerpo", "calmar", "luminosidad", "barrera"],
    "pelo": ["brillo", "reparar", "encrespamiento", "caspa", "cuero_graso", "caida", "volumen",
             "hidratacion_pelo", "calmar"],
}

# Lo que puede escribir el usuario (o el LLM) -> etiqueta del catálogo
SINONIMOS = {
    "acne": "acne", "granos": "acne", "granitos": "acne", "imperfecciones": "acne", "espinillas": "acne",
    "puntos negros": "poros", "poros abiertos": "poros", "hinchazon": "ojeras", "ojos": "ojeras",
    "arrugas": "antiedad", "lineas de expresion": "antiedad", "flacidez": "antiedad",
    "deshidratacion": "hidratacion", "tirantez": "hidratacion", "irritacion": "calmar", "picor": "calmar",
    "rojeces": "rojeces", "rosacea": "rojeces", "cicatrices": "manchas", "marcas": "manchas",
    "piel apagada": "luminosidad", "brillo piel": "luminosidad", "glass skin": "luminosidad",
    "acneica": "acneica", "con acne": "acneica",
    "grasa": "grasa", "grasienta": "grasa", "seca": "seca", "mixta": "mixta", "normal": "normal",
    "sensible": "sensible", "reactiva": "sensible", "madura": "madura", "atopica": "atopica",
    "no comedogenico": "no_comedogenico", "no comedogenica": "no_comedogenico",
    "sin perfume": "sin_perfume", "sin fragancia": "sin_perfume",
    "brillo": "brillo", "que de brillo": "aporta_brillo", "aporta brillo": "aporta_brillo",
    "glow": "luminosidad", "luminosa": "luminosidad", "luminoso": "luminosidad", "apagada": "luminosidad",
    "manchas": "manchas", "quite manchas": "manchas", "antimanchas": "manchas",
    "arrugas": "antiedad", "antiarrugas": "antiedad", "antiedad": "antiedad",
    "poros": "poros", "puntos negros": "poros", "rojeces": "rojeces", "rojez": "rojeces",
    "hidratante": "hidratacion", "hidratacion": "hidratacion", "deshidratada": "hidratacion",
    "calmante": "calmar", "calmar": "calmar", "barrera": "barrera", "textura": "textura",
    "cara": "cara", "facial": "cara", "rostro": "cara",
    "pelo": "pelo", "cabello": "pelo", "capilar": "pelo", "cuerpo": "cuerpo", "corporal": "cuerpo",
    "cuero cabelludo sensible": "cuero_sensible", "danado": "dañado", "tenido": "teñido",
    "encrespado": "encrespamiento", "bolsas": "ojeras", "ojeras": "ojeras", "contorno de ojos": "ojeras",
    "arrugas finas": "antiedad", "firmeza": "antiedad", "tono": "manchas", "tono irregular": "manchas",
    "puntos": "poros", "sebo": "grasa", "brillos": "grasa", "sequedad": "hidratacion", "frizz": "encrespamiento", "caida": "caida",
    # "Cómo quieres tu piel" escrito en el chat (en inglés skincare o en español)
    "glowy": "luminosidad", "dewy": "hidratacion", "jugosa": "hidratacion", "plumpy": "hidratacion",
    "bouncy": "antiedad", "firme": "antiedad", "clear": "acne", "smooth": "textura", "lisa": "textura",
    "mate": "grasa", "menos grasa": "grasa", "radiante": "luminosidad",
    "uniforme": "manchas", "tono uniforme": "manchas", "even toned": "manchas", "bright": "luminosidad",
    "poreless": "poros", "calmada": "calmar", "sana": "barrera", "menos rojeces": "rojeces",
}

# "Cómo quieres tu piel": palabras generales que la persona elige en su perfil. Cada una se traduce
# a objetivos del optimizador (después de los objetivos concretos, que pesan más) y a una
# preferencia de acabado ('jugoso' evita lo matificante; 'mate' evita lo muy rico).
DESEOS = {
    "glowy":     ("Glowy", "con brillo sano, de dentro afuera", ["luminosidad", "hidratacion"], "jugoso"),
    "dewy":      ("Dewy", "jugosa, con acabado húmedo", ["hidratacion", "luminosidad"], "jugoso"),
    "plumpy":    ("Plumpy", "rellena de agua, sin líneas de deshidratación", ["hidratacion", "barrera"], "jugoso"),
    "bouncy":    ("Bouncy", "elástica, que rebota", ["antiedad", "hidratacion"], ""),
    "clear":     ("Clear", "sin granitos ni puntos negros", ["acne", "poros"], ""),
    "hidratada": ("Hidratada", "", ["hidratacion"], ""),
    "smooth":    ("Smooth", "lisa al tacto", ["textura"], ""),
    "suave":     ("Suave", "", ["textura", "hidratacion"], ""),
    "menos_textura": ("Menos textura", "sin granitos pequeños ni rugosidad", ["textura", "poros"], ""),
    "poros":     ("Poros menos visibles", "", ["poros"], ""),
    "menos_grasa": ("Menos grasa", "", ["grasa"], ""),
    "mate":      ("Mate", "sin brillos", ["grasa", "poros"], "mate"),
    "uniforme":  ("Tono uniforme", "sin manchas ni marcas", ["manchas"], ""),
    "luminosa":  ("Luminosa", "bright, sin piel apagada", ["luminosidad", "manchas"], ""),
    "radiante":  ("Radiante", "", ["luminosidad"], ""),
    "fresca":    ("Fresca", "ligera, sin sensación pesada", ["hidratacion"], "ligero"),
    "firme":     ("Firme", "", ["antiedad"], ""),
    "calmada":   ("Calmada", "", ["calmar"], ""),
    "menos_rojeces": ("Menos rojeces", "", ["rojeces", "calmar"], ""),
    "sana":      ("Sana", "barrera fuerte, que no se irrite", ["barrera"], ""),
}


def objetivos_de_deseos(deseos: list[str]) -> list[str]:
    """Objetivos (sin repetir, en orden) que corresponden a los deseos elegidos."""
    return list(dict.fromkeys(o for d in deseos or [] if d in DESEOS for o in DESEOS[d][2]))


def acabados_de_deseos(deseos: list[str]) -> set[str]:
    return {DESEOS[d][3] for d in deseos or [] if d in DESEOS and DESEOS[d][3]}


# Subtipos de paso para apuntar productos a mano y ordenar la rutina como en cabina:
# limpieza -> tónico -> sérums -> crema -> protector solar.
SUBTIPOS = {
    "limpiador_aceite": ("limpiador_aceite", "Limpieza", "Aceite o bálsamo desmaquillante", []),
    "limpiador_micelar": ("limpiador_aceite", "Limpieza", "Agua micelar o leche desmaquillante", []),
    "limpiador_gel": ("limpiador", "Limpieza", "Gel o espuma limpiadora", []),
    "limpiador_crema": ("limpiador", "Limpieza", "Limpiador en crema", ["hidratacion"]),
    "tonico": ("tonico", "Tónico", "Tónico o esencia", []),
    "serum_hidratante": ("serum", "Sérum", "Hidratante (hialurónico, ceramidas…)", ["hidratacion", "barrera"]),
    "serum_tratamiento": ("serum", "Sérum", "Tratamiento: granitos, poros, grasa", ["acne", "poros"]),
    "serum_antiedad": ("serum", "Sérum", "Antiedad: retinol, péptidos…", ["antiedad"]),
    "serum_smooth": ("serum", "Sérum", "Textura y smooth: ácidos suaves", ["textura"]),
    "serum_luminosidad": ("serum", "Sérum", "Luminosidad y manchas: vitamina C…", ["luminosidad", "manchas"]),
    "serum_calmante": ("serum", "Sérum", "Calmante: centella, rojeces", ["calmar", "rojeces"]),
    "contorno": ("contorno", "Sérum", "Contorno de ojos", ["ojeras"]),
    "hidratante": ("hidratante", "Crema", "Crema hidratante", ["hidratacion"]),
    "spf": ("spf", "Protector solar", "Protector solar", []),
}


def paso_y_objetivos(paso: str) -> tuple[str, list[str]]:
    """'serum_hidratante' -> ('serum', ['hidratacion', 'barrera']). Pasos normales se devuelven igual."""
    if paso in SUBTIPOS:
        return SUBTIPOS[paso][0], list(SUBTIPOS[paso][3])
    return paso, []


def _plano(texto: str) -> str:
    texto = (texto or "").replace("ñ", "\0").lower()
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return " ".join(texto.replace("\0", "ñ").replace("-", " ").replace("_", " ").split())


def interpretar(texto: str, validos: tuple | list) -> list[str]:
    """Entiende lo que la persona quiso decir aunque lo escriba mal o junte varias cosas.

    'bolsas-ojeras' -> ['ojeras'];  'manchas y rojeces' -> ['manchas', 'rojeces'];
    'granitoss' -> ['acne'];  'luminosidaz' -> ['luminosidad'].
    Si se equivoca, la persona lo corrige en el chat ("no, me refería a...").
    """
    validos = list(validos)
    entero = normalizar(texto)
    if entero in validos:
        return [entero]
    # Sinónimos de varias palabras ("puntos negros", "tono irregular") antes de trocear
    plano = _plano(texto)
    encontrados = [v for clave, v in SINONIMOS.items() if " " in clave and clave in plano and v in validos]
    trozos = [t for t in re.split(r"[\s,;/+&]+|\by\b|\be\b|\bcon\b", plano) if len(t) > 2]
    candidatos = {**{v.replace("_", " "): v for v in validos},
                  **{k: v for k, v in SINONIMOS.items() if v in validos}}
    for trozo in trozos:
        t = SINONIMOS.get(trozo, trozo).replace(" ", "_")
        if t in validos:
            encontrados.append(t)
            continue
        parecido = difflib.get_close_matches(trozo, list(candidatos), n=1, cutoff=0.75)
        if parecido:
            encontrados.append(candidatos[parecido[0]])
        else:  # 'bolsas_ojeras' troceado no da nada: probar si contiene un valor válido
            encontrados += [v for v in validos if len(v) > 3 and v in t]
    return list(dict.fromkeys(encontrados))


def normalizar(valor: str) -> str:
    """'No comedogénico' -> 'no_comedogenico'; 'acné' -> 'acne'."""
    limpio = _plano(valor)
    return SINONIMOS.get(limpio, limpio.replace(" ", "_"))


# ---------- Carga ----------

def _desde_fila(fila: dict) -> dict:
    p = {k: (v or "").strip() for k, v in fila.items()}
    for campo in LISTAS:
        p[campo] = [x.strip() for x in p[campo].split("|") if x.strip()]
    p["precio"] = float(p["precio"]) if p["precio"] else None
    p["fuente"] = "curado"
    return p


@lru_cache
def cargar_productos() -> tuple[dict, ...]:
    with open(CATALOGO, encoding="utf-8") as f:
        productos = {p["id"]: p for p in map(_desde_fila, csv.DictReader(f, delimiter=";"))}

    # Productos importados (no sobrescriben a los curados)
    for fichero in sorted(CARPETA_IMPORTADOS.glob("productos_*.json")):
        for p in json.loads(fichero.read_text(encoding="utf-8")):
            productos.setdefault(p["id"], p)

    # Imágenes: data/imagenes.json (las que añadas a mano) y las de Open Beauty Facts
    for fichero in (CATALOGO.parent / "imagenes.json", CARPETA_IMPORTADOS / "imagenes_openbeautyfacts.json"):
        if fichero.exists():
            for id_, img in json.loads(fichero.read_text(encoding="utf-8")).items():
                if isinstance(img, dict) and id_ in productos and img.get("url") and not productos[id_].get("imagen"):
                    productos[id_]["imagen"] = img["url"]
                    productos[id_]["imagen_fuente"] = img.get("fuente", "")

    # Activos detectados en Open Beauty Facts para productos del catálogo
    inci = CARPETA_IMPORTADOS / "inci_openbeautyfacts.json"
    if inci.exists():
        for id_, datos in json.loads(inci.read_text(encoding="utf-8")).items():
            if id_ in productos:
                extra = [a for a in datos.get("activos", []) if a not in productos[id_]["activos"]]
                productos[id_]["activos"] = productos[id_]["activos"] + extra
                productos[id_]["inci"] = datos.get("inci", "")

    # Momento del día según la matriz de compatibilidad: un sérum con retinol va de noche y uno con
    # vitamina C pura, de día (salvo que el catálogo ya diga otra cosa)
    from app import ingredientes
    for p in productos.values():
        if p.get("momento", "ambos") in ("", "ambos") and p["zona"] == "cara" \
                and p["paso"] not in ("limpiador", "limpiador_aceite", "spf"):
            p["momento"] = ingredientes.momento(p["activos"])
    return tuple(productos.values())


@lru_cache
def _indice() -> dict:
    return {p["id"]: p for p in cargar_productos()}


def producto_por_id(producto_id: str) -> dict | None:
    return _indice().get(producto_id)


@lru_cache
def tiendas() -> dict:
    return json.loads(TIENDAS.read_text(encoding="utf-8"))["tiendas"]


def enlaces(p: dict) -> list[dict]:
    """Enlaces de compra: los que trae el producto + búsquedas en las tiendas donde suele estar."""
    consulta = quote_plus(f"{p['marca']} {p['nombre']}")
    lista = [dict(e) for e in p.get("enlaces", [])]
    for clave in p.get("tiendas", []):
        if clave in tiendas():
            t = tiendas()[clave]
            lista.append({"tienda": t["nombre"], "tipo": t["tipo"],
                          "url": t["url"].replace("{q}", consulta)})
    return lista


def vocabulario() -> dict[str, list[str]]:
    productos = cargar_productos()
    return {
        "zona": sorted({p["zona"] for p in productos}),
        "paso": sorted({p["paso"] for p in productos}),
        "apto_para": sorted({t for p in productos for t in p["apto_para"]}),
        "caracteristicas": sorted({c for p in productos for c in p["caracteristicas"]}),
        "objetivos": OBJETIVOS,
    }


# ---------- Búsqueda por texto (armario, "merece la pena") ----------

def buscar_texto(consulta: str, limite: int = 8, zona: str = "", paso: str = "") -> list[tuple[float, dict]]:
    """Busca por marca y nombre tolerando erratas. Devuelve [(puntuación 0-1, producto)]."""
    q = _plano(consulta)
    if not q:
        return []
    palabras = set(q.split())
    resultados = []
    for p in cargar_productos():
        if (zona and p["zona"] != zona) or (paso and p["paso"] != paso):
            continue
        texto = _plano(f"{p['marca']} {p['nombre']}")
        comunes = palabras & set(texto.split())
        solape = len(comunes) / len(palabras)
        parecido = difflib.SequenceMatcher(None, q, texto).ratio()
        puntuacion = 0.6 * solape + 0.4 * parecido + (0.2 if q in texto else 0)
        if puntuacion > 0.3:
            resultados.append((round(min(puntuacion, 1.0), 3), p))
    resultados.sort(key=lambda x: -x[0])
    return resultados[:limite]


# ---------- Filtros para el buscador del asesor ----------

def texto_para_embedding(p: dict) -> str:
    from app import ingredientes

    return (
        f"{p['marca']} {p['nombre']}. {p['paso'].replace('_', ' ')} para {p['zona']}. "
        f"{p['descripcion']} Apto para: {', '.join(p['apto_para'])}. "
        f"Objetivos: {', '.join(p['objetivos'])}. "
        f"Características: {', '.join(c.replace('_', ' ') for c in p['caracteristicas'])}. "
        f"Ingredientes clave: {', '.join(ingredientes.nombre(a) for a in p['activos'])}."
    )


def filtro_chroma(zona: str = "", precio_min: float = 0, precio_max: float = 0) -> dict | None:
    """Filtro de metadatos para ChromaDB (solo campos escalares)."""
    condiciones = []
    if zona:
        condiciones.append({"zona": {"$eq": normalizar(zona)}})
    if precio_min:
        condiciones.append({"precio": {"$gte": float(precio_min)}})
    if precio_max:
        condiciones.append({"precio": {"$lte": float(precio_max)}})
    if not condiciones:
        return None
    return condiciones[0] if len(condiciones) == 1 else {"$and": condiciones}


def apto(p: dict, tipo: str) -> bool:
    return not tipo or "todas" in p["apto_para"] or normalizar(tipo) in p["apto_para"]


def cumple_filtros(p: dict, zona: str = "", apto_para: list[str] | None = None,
                   objetivos: list[str] | None = None, caracteristicas: list[str] | None = None,
                   precio_min: float = 0, precio_max: float = 0,
                   evitar_ingredientes: list[str] | None = None, solo_coreano: bool = False) -> bool:
    from app import ingredientes

    if zona and p["zona"] != normalizar(zona):
        return False
    if solo_coreano and p["origen"] != "kr":
        return False
    if (precio_min or precio_max) and p["precio"] is None:
        return False
    if precio_min and p["precio"] < precio_min:
        return False
    if precio_max and p["precio"] > precio_max:
        return False
    if any(not apto(p, t) for t in apto_para or []):
        return False
    if any(normalizar(o) not in p["objetivos"] for o in objetivos or []):
        return False
    if any(normalizar(c) not in p["caracteristicas"] for c in caracteristicas or []):
        return False
    if evitar_ingredientes and set(p["activos"]) & ingredientes.ids_desde_texto(evitar_ingredientes):
        return False
    return True


def resumen(p: dict) -> dict:
    """Datos de un producto para la web y para la rutina."""
    from app import ingredientes

    return {
        "id": p["id"], "marca": p["marca"], "nombre": p["nombre"], "origen": p["origen"],
        "zona": p["zona"], "paso": p["paso"], "precio": p["precio"], "tamano": p.get("tamano", ""),
        "objetivos": p["objetivos"], "caracteristicas": p["caracteristicas"],
        "activos": [ingredientes.nombre(a) for a in p["activos"] if a != "uv-filters"],
        "descripcion": p.get("descripcion", ""), "enlaces": enlaces(p), "fuente": p.get("fuente", ""),
        "imagen": p.get("imagen", ""), "imagen_fuente": p.get("imagen_fuente", ""),
        "ingredientes": [{"nombre": ingredientes.nombre(a), "que_hace": ingredientes.explicacion(a)}
                         for a in p["activos"] if a not in ("uv-filters", "glycerin")],
        "momento": p.get("momento", "ambos"),
    }


def ficha(p: dict) -> str:
    """Texto compacto de un producto para pasárselo al LLM."""
    from app import ingredientes

    precio = f"{p['precio']:.2f} € aprox." if p["precio"] else "precio no disponible"
    return (
        f"- [ref:{p['id']}] {p['marca']} · {p['nombre']} ({p['paso']}, {p['zona']}, "
        f"{'K-beauty' if p['origen'] == 'kr' else p['origen'].upper()}) · {precio}\n"
        f"  Apto para: {', '.join(p['apto_para'])} | Objetivos: {', '.join(p['objetivos'])} | "
        f"{', '.join(p['caracteristicas'])}\n"
        f"  Ingredientes clave: {', '.join(ingredientes.nombre(a) for a in p['activos'])}\n"
        f"  {p.get('descripcion', '')} Tiendas: {', '.join(e['tienda'] for e in enlaces(p))}"
    )
