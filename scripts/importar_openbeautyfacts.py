"""Completa los ingredientes (INCI) del catálogo con Open Beauty Facts.

Fuente: https://world.openbeautyfacts.org/data  — exportación CSV completa (tabulada, gzip).
Licencia: Open Database License (ODbL). Atribución: "Contiene datos de Open Beauty Facts,
disponibles bajo la Open Database License". Si publicas una versión modificada de esos datos,
debe seguir bajo ODbL.

Qué hace: también guarda la FOTO del producto (licencia CC BY-SA) para mostrarla en la web.
Recorre la exportación (sin cargarla entera en memoria), busca los productos de
las mismas marcas que nuestro catálogo, empareja por parecido del nombre y traduce la lista
de ingredientes a los ids del dataset de ingredientes. Así el optimizador detecta perfume,
alcohol, aceites comedogénicos... aunque no estén en nuestras fichas.

Uso:
    python -m scripts.importar_openbeautyfacts                       # descarga (~100+ MB)
    python -m scripts.importar_openbeautyfacts --fichero en.openbeautyfacts.org.products.csv.gz
Después: python -m app.ingesta
"""

import argparse
import csv
import difflib
import gzip
import io
import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import catalogo, ingredientes  # noqa: E402

URL = "https://static.openbeautyfacts.org/data/en.openbeautyfacts.org.products.csv.gz"
SALIDA = RAIZ / "data" / "importados" / "inci_openbeautyfacts.json"
SALIDA_IMAGENES = RAIZ / "data" / "importados" / "imagenes_openbeautyfacts.json"
UMBRAL = 0.72          # parecido mínimo entre nombres para dar por bueno el emparejamiento


def _plano(texto: str) -> str:
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() else " " for c in texto).split())


def _indice_inci() -> dict[str, str]:
    """Nombre INCI / común / alias (normalizado) -> id del dataset."""
    indice = {}
    for id_ in ingredientes.todos_los_ids():
        i = ingredientes.info(id_)
        for nombre in [i.get("inci_name"), i.get("common_name"), *i.get("also_known_as", [])]:
            if nombre and len(_plano(nombre)) > 3:
                indice[_plano(nombre)] = id_
    return indice


def activos_desde_inci(texto: str, indice: dict[str, str]) -> list[str]:
    encontrados = []
    for trozo in texto.replace(";", ",").split(","):
        t = _plano(trozo)
        if not t:
            continue
        id_ = indice.get(t) or next((v for k, v in indice.items() if len(k) > 6 and k in t), None)
        if id_ and id_ not in encontrados:
            encontrados.append(id_)
    return encontrados


def emparejar(filas, productos=None) -> dict[str, dict]:
    """filas: diccionarios con product_name, brands, ingredients_text y code."""
    productos = productos or [p for p in catalogo.cargar_productos() if p.get("fuente") == "curado"]
    por_marca: dict[str, list[dict]] = {}
    for p in productos:
        por_marca.setdefault(_plano(p["marca"]), []).append(p)
    indice = _indice_inci()
    mejores: dict[str, dict] = {}
    for fila in filas:
        texto_inci = fila.get("ingredients_text") or ""
        if not texto_inci or not fila.get("product_name"):
            continue
        marcas = {_plano(m) for m in (fila.get("brands") or "").split(",")}
        nombre = _plano(fila["product_name"])
        for marca in marcas & set(por_marca):
            for p in por_marca[marca]:
                parecido = difflib.SequenceMatcher(None, nombre, _plano(p["nombre"])).ratio()
                if parecido >= UMBRAL and parecido > mejores.get(p["id"], {}).get("similitud", 0):
                    mejores[p["id"]] = {
                        "similitud": round(parecido, 3), "inci": texto_inci[:3000],
                        "activos": activos_desde_inci(texto_inci, indice),
                        "url": f"https://world.openbeautyfacts.org/product/{fila.get('code', '')}",
                        "imagen": fila.get("image_front_url") or fila.get("image_url") or "",
                    }
    return mejores


def _leer_csv(fichero) -> csv.DictReader:
    csv.field_size_limit(10**8)
    texto = io.TextIOWrapper(gzip.GzipFile(fileobj=fichero), encoding="utf-8", errors="replace")
    return csv.DictReader(texto, delimiter="\t", quoting=csv.QUOTE_NONE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fichero", help="CSV .gz ya descargado (si no, se descarga)")
    args = parser.parse_args()
    if args.fichero:
        with open(args.fichero, "rb") as f:
            resultado = emparejar(_leer_csv(f))
    else:
        print(f"Descargando {URL} (puede tardar) ...", file=sys.stderr)
        peticion = urllib.request.Request(URL, headers={"User-Agent": "dear-skin-importer"})
        with urllib.request.urlopen(peticion, timeout=600) as respuesta:
            resultado = emparejar(_leer_csv(respuesta))
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    imagenes = {pid: {"url": d["imagen"], "fuente": "Open Beauty Facts (CC BY-SA)"}
                for pid, d in resultado.items() if d.get("imagen")}
    SALIDA_IMAGENES.write_text(json.dumps(imagenes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"INCI encontrado para {len(resultado)} productos y foto para {len(imagenes)} -> {SALIDA.parent}")
    print("Contiene datos de Open Beauty Facts, disponibles bajo la Open Database License (ODbL).")


if __name__ == "__main__":
    main()
