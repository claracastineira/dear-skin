"""Importadores de fuentes abiertas, con datos de ejemplo (sin descargar nada)."""

import gzip
import io

from scripts import importar_kbeautyanswers as kba
from scripts import importar_openbeautyfacts as obf

MUESTRA_KBA = {"count": 4, "products": [
    {"slug": "anua-heartleaf-77-soothing-toner", "name_en": "Heartleaf 77% Soothing Toner",
     "brand_en": "Anua", "category_path": ["화장품/미용", "스킨케어", "스킨/토너"], "price_krw": 27000,
     "buy_worldwide": [{"channel": "yesstyle", "label": "YesStyle", "url": "https://example.com/anua"}]},
    {"slug": "x-retinol-cream", "name_en": "The Retinol 0.1 Cream", "brand_en": "COSRX",
     "category_path": ["화장품/미용", "스킨케어", "크림"], "price_usd": 20},
    {"slug": "y-cushion", "name_en": "Glow Cushion SPF50", "brand_en": "Clio",
     "category_path": ["화장품/미용", "베이스메이크업", "쿠션"]},
    {"slug": "z-shampoo", "name_en": "Rosemary Scalp Shampoo", "brand_en": "Aromatica",
     "category_path": ["화장품/미용", "헤어케어", "샴푸"], "price_krw": 18000},
]}


def test_kbeautyanswers():
    productos = {p["id"]: p for p in kba.importar(MUESTRA_KBA)}
    assert len(productos) == 3                                     # el cushion es maquillaje
    tonico = productos["kba-anua-heartleaf-77-soothing-toner"]
    assert (tonico["zona"], tonico["paso"]) == ("cara", "tonico")
    assert "houttuynia-cordata" in tonico["activos"] and "calmar" in tonico["objetivos"]
    assert tonico["precio"] == 18.0 and tonico["enlaces"][0]["tienda"] == "YesStyle"
    retinol = productos["kba-x-retinol-cream"]
    assert retinol["activos"] == ["retinol"] and retinol["momento"] == "pm" and retinol["precio"] == 18.4
    assert productos["kba-z-shampoo"]["paso"] == "champu"
    assert kba.convertir({"name_en": "Phase Toner", "brand_en": "X", "category_path": ["토너"]})["activos"] == []


def test_openbeautyfacts():
    filas = [
        {"product_name": "Relief Sun Rice + Probiotics", "brands": "Beauty of Joseon", "code": "123",
         "ingredients_text": "Water, Oryza Sativa (Rice) Extract, Niacinamide, Glycerin, Parfum"},
        {"product_name": "Otra cosa distinta", "brands": "Beauty of Joseon", "code": "9",
         "ingredients_text": "Water, Retinol"},
    ]
    resultado = obf.emparejar(filas)
    datos = resultado["boj-relief-sun"]
    assert {"niacinamide", "glycerin", "fragrance"} <= set(datos["activos"])
    assert datos["url"].endswith("/123") and datos["similitud"] >= obf.UMBRAL


def test_lectura_csv_gz():
    contenido = "code\tproduct_name\tbrands\tingredients_text\n1\tX\tY\tWater, Niacinamide\n"
    gz = io.BytesIO(gzip.compress(contenido.encode()))
    filas = list(obf._leer_csv(gz))
    assert filas[0]["ingredients_text"] == "Water, Niacinamide"
