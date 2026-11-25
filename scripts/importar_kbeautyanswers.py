"""Importa miles de productos coreanos desde el dataset abierto de K-Beauty Answers.

Fuente: https://kbeautyanswers.com/dataset/  (API JSON sin clave: /api/products.json)
Licencia del contenido editorial: CC BY 4.0 (cita: "K-Beauty Answers. K-Beauty AI Citation
Dataset"). Los precios y las imágenes son de los vendedores: por eso el fichero generado
NO se sube a GitHub (está en .gitignore) y cada persona lo genera en su ordenador.

El dataset no trae ingredientes (INCI), así que se deducen del nombre del producto
("Heartleaf 77% Toner" -> heartleaf; "Retinol 0.1 Cream" -> retinol). Los productos
importados se marcan con fuente="kbeautyanswers"; el optimizador puede usarlos igual
que los curados, pero conviene revisarlos.

Uso:
    python -m scripts.importar_kbeautyanswers                 # descarga y convierte
    python -m scripts.importar_kbeautyanswers --fichero products.json
Después: python -m app.ingesta
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
URL = "https://kbeautyanswers.com/api/products.json"
SALIDA = RAIZ / "data" / "importados" / "productos_kbeautyanswers.json"
EUR_POR_KRW = 1 / 1500      # cambio aproximado; el precio importado es orientativo
EUR_POR_USD = 0.92

# (palabra en la categoría coreana o en el nombre inglés) -> (zona, paso). El orden importa.
CATEGORIAS = [
    ("헤어오일", "pelo", "tratamiento_capilar"), ("헤어에센스", "pelo", "tratamiento_capilar"),
    ("헤어세럼", "pelo", "tratamiento_capilar"), ("두피", "pelo", "cuero_cabelludo"),
    ("샴푸", "pelo", "champu"), ("린스", "pelo", "acondicionador"), ("컨디셔너", "pelo", "acondicionador"),
    ("트리트먼트", "pelo", "mascarilla_capilar"), ("헤어팩", "pelo", "mascarilla_capilar"),
    ("바디워시", "cuerpo", "gel_corporal"), ("바디로션", "cuerpo", "hidratante_corporal"),
    ("바디크림", "cuerpo", "hidratante_corporal"), ("바디오일", "cuerpo", "tratamiento_corporal"),
    ("바디스크럽", "cuerpo", "tratamiento_corporal"),
    ("클렌징오일", "cara", "limpiador_aceite"), ("클렌징밤", "cara", "limpiador_aceite"),
    ("클렌징", "cara", "limpiador"), ("스킨/토너", "cara", "tonico"), ("토너", "cara", "tonico"),
    ("패드", "cara", "tonico"), ("선케어", "cara", "spf"), ("선크림", "cara", "spf"),
    ("에센스", "cara", "serum"), ("세럼", "cara", "serum"), ("앰플", "cara", "serum"),
    ("로션", "cara", "hidratante"), ("크림", "cara", "hidratante"), ("마스크", "cara", "mascarilla"),
    # Si la categoría no ayuda, se mira el nombre en inglés
    ("hair oil", "pelo", "tratamiento_capilar"), ("hair serum", "pelo", "tratamiento_capilar"),
    ("scalp", "pelo", "cuero_cabelludo"), ("shampoo", "pelo", "champu"),
    ("conditioner", "pelo", "acondicionador"), ("hair mask", "pelo", "mascarilla_capilar"),
    ("body wash", "cuerpo", "gel_corporal"), ("body lotion", "cuerpo", "hidratante_corporal"),
    ("body cream", "cuerpo", "hidratante_corporal"), ("body oil", "cuerpo", "tratamiento_corporal"),
    ("cleansing oil", "cara", "limpiador_aceite"), ("cleansing balm", "cara", "limpiador_aceite"),
    ("cleanser", "cara", "limpiador"), ("cleansing foam", "cara", "limpiador"),
    ("toner", "cara", "tonico"), ("pad", "cara", "tonico"), ("sun", "cara", "spf"),
    ("spf", "cara", "spf"), ("essence", "cara", "esencia"), ("serum", "cara", "serum"),
    ("ampoule", "cara", "serum"), ("cream", "cara", "hidratante"), ("lotion", "cara", "hidratante"),
    ("moisturizer", "cara", "hidratante"), ("mask", "cara", "mascarilla"),
]
MAQUILLAJE = ("cushion", "foundation", "lip", "tint", "mascara", "eyeliner", "brow", "blush",
              "concealer", "palette", "powder", "쿠션", "파운데이션", "립", "틴트", "메이크업")

# palabra en el nombre -> activo (id del dataset de ingredientes)
ACTIVOS = [
    ("pure vitamin c", "ascorbic-acid"), ("vitamin c", "ethyl-ascorbic-acid"), ("vita c", "ethyl-ascorbic-acid"),
    ("retinal", "retinaldehyde"), ("retinol", "retinol"), ("bakuchiol", "bakuchiol"),
    ("niacinamide", "niacinamide"), ("heartleaf", "houttuynia-cordata"), ("houttuynia", "houttuynia-cordata"),
    ("centella", "centella-asiatica"), ("cica", "centella-asiatica"), ("madecassoside", "madecassoside"),
    ("snail", "snail-mucin"), ("propolis", "propolis-extract"), ("rice", "rice-extract"),
    ("ceramide", "ceramide-np"), ("hyaluron", "hyaluronic-acid"), ("salicylic", "salicylic-acid"),
    ("bha", "salicylic-acid"), ("glycolic", "glycolic-acid"), ("aha", "glycolic-acid"),
    ("pha", "gluconolactone"), ("mugwort", "mugwort-extract"), ("artemisia", "mugwort-extract"),
    ("tea tree", "tea-tree-oil"), ("panthenol", "panthenol"), ("peptide", "peptide-complex-tripeptide-1"),
    ("collagen", "hydrolyzed-collagen"), ("pdrn", "pdrn"), ("azelaic", "azelaic-acid"),
    ("tranexamic", "tranexamic-acid"), ("txa", "tranexamic-acid"), ("glutathione", "glutathione"),
    ("ginseng", "ginseng-extract"), ("birch", "birch-sap"), ("green tea", "green-tea-extract"),
    ("arbutin", "alpha-arbutin"), ("beta-glucan", "beta-glucan"), ("beta glucan", "beta-glucan"),
    ("mandelic", "mandelic-acid"), ("lactic", "lactic-acid"), ("galactomyces", "galactomyces-ferment"),
    ("aloe", "aloe-vera"), ("squalane", "squalane"), ("argan", "argan-oil"), ("rosemary", "rosemary-extract"),
    ("keratin", "hydrolyzed-keratin"), ("sun", "uv-filters"), ("spf", "uv-filters"),
]
OBJETIVOS_POR_ACTIVO = {
    "niacinamide": ["poros", "manchas", "luminosidad"], "retinol": ["antiedad", "textura"],
    "retinaldehyde": ["antiedad", "textura"], "bakuchiol": ["antiedad"],
    "salicylic-acid": ["acne", "poros"], "glycolic-acid": ["textura", "luminosidad"],
    "gluconolactone": ["textura"], "mandelic-acid": ["textura", "acne"], "lactic-acid": ["textura"],
    "ascorbic-acid": ["manchas", "luminosidad"], "ethyl-ascorbic-acid": ["manchas", "luminosidad"],
    "centella-asiatica": ["calmar", "rojeces"], "madecassoside": ["calmar", "barrera"],
    "houttuynia-cordata": ["calmar", "acne"], "snail-mucin": ["hidratacion", "barrera"],
    "hyaluronic-acid": ["hidratacion"], "ceramide-np": ["barrera", "hidratacion"],
    "propolis-extract": ["luminosidad", "calmar"], "rice-extract": ["luminosidad"],
    "mugwort-extract": ["calmar"], "tea-tree-oil": ["acne"], "panthenol": ["calmar", "barrera"],
    "peptide-complex-tripeptide-1": ["antiedad"], "hydrolyzed-collagen": ["antiedad", "hidratacion"],
    "pdrn": ["antiedad"], "azelaic-acid": ["rojeces", "acne"], "tranexamic-acid": ["manchas"],
    "alpha-arbutin": ["manchas"], "glutathione": ["manchas", "luminosidad"],
    "ginseng-extract": ["antiedad", "luminosidad"], "birch-sap": ["hidratacion"],
    "green-tea-extract": ["calmar", "grasa"], "beta-glucan": ["hidratacion", "calmar"],
    "galactomyces-ferment": ["luminosidad"], "aloe-vera": ["calmar", "hidratacion"],
    "squalane": ["hidratacion"], "uv-filters": ["proteccion_solar"],
    "argan-oil": ["brillo", "encrespamiento"], "hydrolyzed-keratin": ["reparar"],
    "rosemary-extract": ["caida"],
}


def _patron(palabra: str) -> str:
    """Palabra completa, admitiendo plural o "-ic" (peptide(s), hyaluron(ic)); 'pha' no casa con 'phase'."""
    return rf"\b{re.escape(palabra)}(?:s|ic)?\b"


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")[:60]


def clasificar(producto: dict) -> tuple[str, str] | None:
    """(zona, paso) a partir de la categoría coreana y del nombre en inglés. None si es maquillaje."""
    categoria = " ".join(producto.get("category_path") or [])
    nombre = (producto.get("name_en") or "").lower()
    if any(m in categoria or m in nombre for m in MAQUILLAJE):
        return None
    for clave, zona, paso in CATEGORIAS:
        if clave in categoria or (clave.isascii() and re.search(_patron(clave), nombre)):
            return zona, paso
    return None


def precio_eur(producto: dict) -> float | None:
    usd = producto.get("price_usd") or producto.get("last_known_price_usd")
    if usd:
        return round(float(usd) * EUR_POR_USD, 2)
    krw = producto.get("price_krw") or producto.get("last_known_price_krw")
    return round(float(krw) * EUR_POR_KRW, 2) if krw else None


def convertir(producto: dict) -> dict | None:
    """Convierte un producto de K-Beauty Answers al esquema del catálogo de Dear Skin."""
    nombre = producto.get("name_en") or producto.get("name_ko")
    marca = producto.get("brand_en") or producto.get("brand_ko")
    clase = clasificar(producto)
    if not nombre or not marca or not clase:
        return None
    zona, paso = clase
    texto = nombre.lower()
    activos = list(dict.fromkeys(a for palabra, a in ACTIVOS if re.search(_patron(palabra), texto)))
    if paso != "spf":
        activos = [a for a in activos if a != "uv-filters"]
    elif "uv-filters" not in activos:
        activos.insert(0, "uv-filters")
    if "ascorbic-acid" in activos and "ethyl-ascorbic-acid" in activos:
        activos.remove("ethyl-ascorbic-acid")
    objetivos = list(dict.fromkeys(o for a in activos for o in OBJETIVOS_POR_ACTIVO.get(a, [])))
    if paso in ("limpiador", "limpiador_aceite"):
        objetivos.append("limpieza")
    apto = ["grasa", "mixta", "acneica", "normal"] if {"salicylic-acid", "tea-tree-oil"} & set(activos) \
        else ["todas"]
    momento = "pm" if {"retinol", "retinaldehyde"} & set(activos) else \
        "am" if "ascorbic-acid" in activos or paso == "spf" else "ambos"
    caracteristicas = []
    if re.search(r"fragrance[- ]free|unscented", texto):
        caracteristicas.append("sin_perfume")
    if "vegan" in texto:
        caracteristicas.append("vegano")
    enlaces = [{"tienda": e.get("label") or e.get("channel") or "Tienda", "tipo": "K-beauty",
                "url": e["url"]} for e in (producto.get("buy_worldwide") or []) if e.get("url")]
    identificador = producto.get("slug") or producto.get("id") or f"{marca}-{nombre}"
    return {
        "id": "kba-" + _slug(str(identificador)), "marca": marca, "nombre": nombre, "origen": "kr",
        "zona": zona, "paso": paso, "momento": momento, "precio": precio_eur(producto), "tamano": "",
        "apto_para": apto, "objetivos": objetivos, "caracteristicas": caracteristicas, "activos": activos,
        "tiendas": ["oliveyoung", "amazon"], "enlaces": enlaces,
        "descripcion": "Importado de K-Beauty Answers (CC BY 4.0). Ingredientes deducidos del nombre; "
                       "precio orientativo convertido desde Corea.",
        "fuente": "kbeautyanswers",
    }


def importar(datos: dict | list) -> list[dict]:
    lista = datos.get("products", []) if isinstance(datos, dict) else datos
    convertidos, vistos = [], set()
    for producto in lista:
        p = convertir(producto)
        if p and p["id"] not in vistos:
            vistos.add(p["id"])
            convertidos.append(p)
    return convertidos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fichero", help="products.json ya descargado (si no, se descarga)")
    args = parser.parse_args()
    if args.fichero:
        datos = json.loads(Path(args.fichero).read_text(encoding="utf-8"))
    else:
        print(f"Descargando {URL} ...", file=sys.stderr)
        peticion = urllib.request.Request(URL, headers={"User-Agent": "dear-skin-importer"})
        with urllib.request.urlopen(peticion, timeout=120) as respuesta:
            datos = json.load(respuesta)
    productos = importar(datos)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(productos, ensure_ascii=False, indent=1), encoding="utf-8")
    por_zona = {}
    for p in productos:
        por_zona[p["zona"]] = por_zona.get(p["zona"], 0) + 1
    print(f"Importados {len(productos)} productos {por_zona} en {SALIDA}")
    print("Ahora ejecuta: python -m app.ingesta")


if __name__ == "__main__":
    main()
