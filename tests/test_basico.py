"""Catálogo, ingredientes y reseñas (sin LLM ni ChromaDB):  python -m pytest"""

from app import catalogo, ingredientes, resenas


def test_catalogo_valido():
    # Solo el catálogo curado: los importados pueden venir sin precio
    productos = [p for p in catalogo.cargar_productos() if p.get("fuente") == "curado"]
    assert len(productos) >= 140
    assert len({p["id"] for p in productos}) == len(productos)
    assert sum(p["origen"] == "kr" for p in productos) > len(productos) / 2   # sobre todo K-beauty
    for p in productos:
        assert p["zona"] in {"cara", "cuerpo", "pelo"}
        assert p["precio"] and p["precio"] > 0
        assert p["tiendas"], p["id"]


def test_enlaces_de_compra():
    p = catalogo.producto_por_id("boj-relief-sun")
    urls = [e["url"] for e in catalogo.enlaces(p)]
    assert any("oliveyoung" in u for u in urls)
    assert all("Beauty+of+Joseon" in u for u in urls)


def test_buscar_texto_tolera_erratas():
    _, p = catalogo.buscar_texto("anua heartlef toner")[0]
    assert p["id"] == "anua-heartleaf-77-toner"


def test_normalizar():
    assert catalogo.normalizar("No comedogénico") == "no_comedogenico"
    assert catalogo.normalizar("acné") == "acne"
    assert catalogo.normalizar("Teñido") == "teñido"


def test_filtros():
    ids = {p["id"] for p in catalogo.cargar_productos()
           if catalogo.cumple_filtros(p, "cara", ["mixta"], ["manchas"], precio_min=40, precio_max=60)}
    assert "caudalie-vinoperfect" in ids
    assert all(catalogo.producto_por_id(i)["precio"] <= 60 for i in ids)
    assert catalogo.filtro_chroma("cara", 40, 60) == {"$and": [
        {"zona": {"$eq": "cara"}}, {"precio": {"$gte": 40.0}}, {"precio": {"$lte": 60.0}}]}


def test_ingredientes():
    assert ingredientes.irritacion(["retinol"]) == 2
    assert ingredientes.irritacion(["salicylic-acid"], aclarado=True) == 0.5
    assert ingredientes.irritacion(["fragrance"], sensible=True) == 1
    assert ingredientes.embarazo(["retinol", "niacinamide"]) == "avoid"
    reglas = ingredientes.conflictos(["retinol"], ["glycolic-acid"])
    assert reglas and reglas[0]["severity"] == "caution"
    assert {"fragrance"} <= ingredientes.ids_desde_texto(["perfume"])
    assert {"retinol", "retinaldehyde", "adapalene"} <= ingredientes.ids_desde_texto(["retinol"])
    assert ingredientes.nombre("niacinamide").startswith("niacinamida")


def test_resenas(bd):
    resenas.inicializar(bd)
    antes = resenas.resumen("to-retinol-05", "mixta", bd)
    assert antes["total"] == 2 and antes["tu_tipo_de_piel"]["total"] == 1
    resenas.guardar_resena({"producto_id": "to-retinol-05", "tipo_piel": "mixta", "puntuacion": 1,
                            "semanas_uso": 10, "reaccion": True, "texto": "picor"}, bd)
    despues = resenas.resumen("to-retinol-05", "mixta", bd)
    assert despues["total"] == 3 and despues["largo_plazo"]["total"] == 2
    assert despues["tu_tipo_de_piel"]["reacciones"] == 1
    assert resenas.resumenes("mixta", bd)["to-retinol-05"]["total"] == 3


def test_interpretar_erratas_y_compuestos():
    OBJETIVOS = tuple(dict.fromkeys(o for lista in catalogo.OBJETIVOS.values() for o in lista))
    i = catalogo.interpretar
    assert i("bolsas-ojeras", OBJETIVOS) == ["ojeras"]
    assert i("bolsas_ojeras", OBJETIVOS) == ["ojeras"]
    assert i("manchas y rojeces", OBJETIVOS) == ["manchas", "rojeces"]
    assert i("granitoss", OBJETIVOS) == ["acne"]
    assert i("luminosidaz", OBJETIVOS) == ["luminosidad"]
    assert i("puntos negros", OBJETIVOS) == ["poros"]
    assert i("Antiedad", OBJETIVOS) == ["antiedad"]
    assert i("xyz", OBJETIVOS) == []
    assert i("mixtaa", ("grasa", "seca", "mixta", "normal")) == ["mixta"]
