from app import compatibilidad, ingredientes, rutina


def test_matriz_reglas_clave():
    assert ingredientes.conflictos(["retinol"], ["glycolic-acid"])[0]["tipo"] == "no_misma_sesion"
    assert ingredientes.conflictos(["ascorbic-acid"], ["benzoyl-peroxide"])[0]["severity"] == "avoid"
    assert ingredientes.sinergias(["retinol"], ["niacinamide"])
    assert not ingredientes.sinergias(["hyaluronic-acid"], ["ceramide-np"])   # sin activo: no cuenta
    assert ingredientes.momento(["retinol"]) == "pm" and ingredientes.momento(["ascorbic-acid"]) == "am"


def test_familias_de_la_matriz_existen():
    m = ingredientes.matriz()
    for r in m["relaciones"]:
        assert r["a"] in m["familias"] and r["b"] in m["familias"] and r["tipo"] in m["tipos"]


def test_comprobador():
    r = compatibilidad.analizar(["retinol", "aha", "niacinamida", "inventadísimo"], "seca", True)
    veredictos = {(p["a"], p["b"]): p["veredicto"] for p in r["pares"]}
    assert "separar" in veredictos.values() and "si" in veredictos.values()
    assert r["no_encontrados"] == ["inventadísimo"]
    assert any(e["momento"] == "Solo de noche" for e in r["elementos"])


def test_rutina_explica_combinaciones():
    r = rutina.optimizar({"tipo_piel": "normal", "objetivos": ["antiedad", "poros"], "max_pasos": 6}, {}, opiniones={})
    assert "combinaciones" in r
