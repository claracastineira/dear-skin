"""¿Se pueden juntar? Comprueba productos o ingredientes contra la matriz de compatibilidad.

Para cada elemento dice qué familias de activos lleva, en qué momento del día va y si encaja con tu
tipo de piel; para cada pareja, si se potencian, si es mejor separarlos (y cómo) o si no se deben juntar.
Lo usan la web (pestaña «¿Se pueden juntar?»), la API y el chat (herramienta MCP).
"""

import itertools

from app import catalogo, ingredientes

MOMENTO_ES = {"noche": "de noche", "manana": "de día", "ambos": "de día o de noche"}
ORDEN_TIPO = {"evitar": 0, "no_misma_sesion": 1, "am_pm": 2, "precaucion": 3, "misma_clase": 4,
              "imprescindible": 5, "sinergia": 6}


ALIAS = {"aha": "glycolic-acid", "acidos aha": "glycolic-acid", "bha": "salicylic-acid", "pha": "gluconolactone",
         "retinal": "retinaldehyde", "retinaldehido": "retinaldehyde", "adapaleno": "adapalene",
         "peroxido de benzoilo": "benzoyl-peroxide", "peroxido": "benzoyl-peroxide",
         "azelaico": "azelaic-acid", "acido azelaico": "azelaic-acid", "tranexamico": "tranexamic-acid",
         "acido tranexamico": "tranexamic-acid", "arbutina": "alpha-arbutin", "kojico": "kojic-acid",
         "acido kojico": "kojic-acid", "pdrn": "pdrn", "caracol": "snail-mucin", "baba de caracol": "snail-mucin",
         "peptidos de cobre": "copper-tripeptide-1", "peptidos": "matrixyl", "ceramidas": "ceramide-np",
         "pantenol": "panthenol", "zinc": "zinc-pca", "arbol de te": "tea-tree-oil", "azufre": "sulfur",
         "acido ferulico": "ferulic-acid", "ferulico": "ferulic-acid", "vitamina e": "tocopherol",
         "bakuchiol": "bakuchiol", "acido lactico": "lactic-acid", "acido mandelico": "mandelic-acid",
         "protector solar": "uv-filters", "spf": "uv-filters", "hidroquinona": "hydroquinone"}


def _resolver(texto: str) -> dict | None:
    """Un texto puede ser un producto del catálogo ("anua niacinamide") o un ingrediente ("retinol")."""
    texto = texto.strip()
    if not texto:
        return None
    # Si es el nombre de un ingrediente o de una familia ("retinol", "vitamina c", "AHA"), es ingrediente
    plano = ingredientes._plano(texto)
    if plano in ALIAS:
        id_ = ALIAS[plano]
        return {"texto": texto, "tipo": "ingrediente", "id": id_, "nombre": ingredientes.nombre(id_),
                "activos": [id_], "imagen": ""}
    if len(plano.split()) <= 3:
        exactos = [i for i in ingredientes.ids_desde_texto([texto])
                   if plano in {ingredientes._plano(n) for n in (i, i.replace("-", " "), ingredientes.nombre(i),
                                                                  ingredientes.info(i).get("common_name", ""))}]
        familia_texto = next((f for f, d in ingredientes.matriz()["familias"].items()
                              if plano in (ingredientes._plano(f.replace("_", " ")),)), None)
        if exactos or plano in ("vitamina c", "aha", "bha", "vitamina a", "acido salicilico", "centella"):
            ids = exactos or sorted(ingredientes.ids_desde_texto([texto]))[:1]
            return {"texto": texto, "tipo": "ingrediente", "id": ids[0], "nombre": ingredientes.nombre(ids[0]),
                    "activos": ids, "imagen": ""}
        if familia_texto:
            ids = ingredientes.familia(familia_texto)["ids"][:1]
            return {"texto": texto, "tipo": "ingrediente", "id": ids[0],
                    "nombre": ingredientes.familia(familia_texto)["nombre"], "activos": ids, "imagen": ""}
    p = catalogo.producto_por_id(texto)
    if not p:
        encontrados = catalogo.buscar_texto(texto, limite=1)
        if encontrados and encontrados[0][0] >= 0.55:
            p = encontrados[0][1]
    if p:
        return {"texto": texto, "tipo": "producto", "id": p["id"], "nombre": f"{p['marca']} {p['nombre']}".strip(),
                "activos": list(p["activos"]), "imagen": p.get("imagen", "")}
    ids = sorted(ingredientes.ids_desde_texto([texto]))
    # "retinol" se expande a todos los retinoides: para mostrar el nombre nos quedamos con el más parecido
    if ids:
        plano = ingredientes._plano(texto)
        principal = next((i for i in ids if plano in ingredientes._plano(ingredientes.nombre(i))
                          or plano in i), ids[0])
        return {"texto": texto, "tipo": "ingrediente", "id": principal,
                "nombre": ingredientes.nombre(principal), "activos": [principal], "imagen": ""}
    return None


def _ficha(elemento: dict, tipo_piel: str, sensible: bool) -> dict:
    fams = sorted(ingredientes.familias(elemento["activos"]) - {"spf"} or ingredientes.familias(elemento["activos"]))
    momento = ingredientes.momento(elemento["activos"])
    notas, avisos = [], []
    tipos = [t for t in (tipo_piel, "sensible" if sensible else "") if t]
    for f in fams:
        datos = ingredientes.familia(f)
        notas.append({"familia": datos["nombre"], "nota": datos.get("nota", ""),
                      "momento": MOMENTO_ES.get(datos.get("momento", "ambos"))})
        delicados = [t for t in tipos if t in datos.get("cuidado", [])]
        if delicados:
            avisos.append(f"{datos['nombre']}: con piel {' y '.join(delicados)}, empieza poco a poco "
                          "y acompáñalo de hidratante.")
    return {**elemento, "familias": notas,
            "momento": {"pm": "Solo de noche", "am": "De día (debajo del protector)", "ambos": "De día o de noche"}[momento],
            "avisos_piel": avisos}


def analizar(elementos: list[str], tipo_piel: str = "", sensible: bool = False) -> dict:
    resueltos, no_encontrados = [], []
    for texto in elementos[:6]:
        r = _resolver(texto)
        (resueltos.append(r) if r else no_encontrados.append(texto))
    fichas = [_ficha(r, tipo_piel, sensible) for r in resueltos]
    pares = []
    for x, y in itertools.combinations(resueltos, 2):
        relaciones = ingredientes.relaciones(x["activos"], y["activos"])
        # Una relación por tipo, la más importante primero
        vistas, lista = set(), []
        for r in sorted(relaciones, key=lambda r: ORDEN_TIPO[r["tipo"]]):
            if r["tipo"] in vistas:
                continue
            vistas.add(r["tipo"])
            lista.append({"tipo": r["tipo"], "titulo": r["titulo"], "porque": r["porque"], "como": r["como"],
                          "familias": [r["nombre_a"], r["nombre_b"]]})
        if lista:
            peor = lista[0]["tipo"]
            veredicto = ("no" if peor == "evitar" else "separar" if peor in ingredientes.SEPARAR
                         else "si")
        else:
            veredicto = "sin_regla"
        pares.append({"a": x["nombre"], "b": y["nombre"], "veredicto": veredicto, "relaciones": lista})
    return {"elementos": fichas, "pares": pares, "no_encontrados": no_encontrados,
            "aviso": ingredientes.matriz()["aviso"], "fuentes": ingredientes.matriz()["fuentes"]}


def texto(resultado: dict) -> str:
    """Resumen en texto para el LLM."""
    lineas = []
    for e in resultado["elementos"]:
        fams = ", ".join(f["familia"] for f in e["familias"]) or "sin activos destacados"
        lineas.append(f"- {e['nombre']}: {fams}. {e['momento']}. {' '.join(e['avisos_piel'])}".strip())
    etiquetas = {"no": "NO JUNTAR", "separar": "MEJOR SEPARADOS", "si": "COMPATIBLES", "sin_regla": "SIN REGLA CONOCIDA"}
    for p in resultado["pares"]:
        lineas.append(f"{p['a']} + {p['b']}: {etiquetas[p['veredicto']]}")
        for r in p["relaciones"]:
            lineas.append(f"   · {r['titulo']}: {r['porque']} {r['como']}")
    if resultado["no_encontrados"]:
        lineas.append("No reconozco: " + ", ".join(resultado["no_encontrados"]))
    lineas.append(resultado["aviso"])
    return "\n".join(lineas)
