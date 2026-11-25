"""Base de conocimiento de ingredientes (Python puro).

Combina el dataset abierto "skincare-ingredients-dataset" (MIT, 128 ingredientes con
irritación, comedogenicidad, seguridad en embarazo y reglas de mezcla) con
data/ingredientes_extra.json (ingredientes típicos de K-beauty y nombres en español).

Lo usan el optimizador de rutinas y el detector de hype para calcular:
irritación acumulada, conflictos entre activos, embarazo e ingredientes a evitar.
"""

import json
import unicodedata
from functools import lru_cache

from app.config import COMPATIBILIDAD, DATASET_INGREDIENTES, INGREDIENTES_EXTRA

IRRITACION = {"low": 0, "medium": 1, "high": 2}

# Grupos de activos "con función": si hay dos productos del mismo grupo en una rutina, es duplicidad
GRUPOS_ACTIVOS = {"retinoids", "aha", "bha", "pha", "vitamin_c_pure", "vitamin_c_derivative",
                  "benzoyl_peroxide", "azelaic", "niacinamide", "copper_peptides"}
# Ingredientes "de relleno" que no cuentan para decidir si dos productos son equivalentes
BASE = {"glycerin", "uv-filters", "fragrance", "dimethicone", "tocopherol", "squalane",
        "hyaluronic-acid", "panthenol", "butylene-glycol", "propanediol"}


def _plano(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").strip()


@lru_cache
def _datos() -> tuple[dict, dict, list]:
    dataset = json.loads((DATASET_INGREDIENTES / "ingredients.json").read_text(encoding="utf-8"))
    reglas = json.loads((DATASET_INGREDIENTES / "compatibility_rules.json").read_text(encoding="utf-8"))
    extra = json.loads(INGREDIENTES_EXTRA.read_text(encoding="utf-8"))

    ingredientes = {i["id"]: dict(i) for i in dataset}
    for i in extra["ingredientes"]:
        ingredientes[i["id"]] = {"common_name": i["nombre_es"], "inci_name": i["id"],
                                 "also_known_as": [], "evidence_level": "limited", **i}
    for id_, nombre in extra["nombres_es"].items():
        if id_ in ingredientes:
            ingredientes[id_]["nombre_es"] = nombre

    grupos: dict[str, set[str]] = {}
    for grupo, ids in reglas["groups"].items():
        for id_ in ids:
            grupos.setdefault(id_, set()).add(grupo)
    for i in extra["ingredientes"]:
        if i.get("grupo"):
            grupos.setdefault(i["id"], set()).add(i["grupo"])
    return ingredientes, grupos, reglas["rules"]


def info(id_: str) -> dict:
    return _datos()[0].get(id_, {"id": id_, "common_name": id_, "irritancy": "low",
                                 "pregnancy_safe": "safe", "evidence_level": "limited"})


def nombre(id_: str) -> str:
    i = info(id_)
    return i.get("nombre_es") or i.get("common_name") or id_


@lru_cache
def _explicaciones() -> dict:
    return json.loads(INGREDIENTES_EXTRA.read_text(encoding="utf-8")).get("explicaciones_es", {})


def explicacion(id_: str) -> str:
    """Una frase sencilla de qué hace el ingrediente ("vitamina B3: regula la grasa...")."""
    return _explicaciones().get(id_, "")


def grupos(id_: str) -> set[str]:
    return _datos()[1].get(id_, set())


def grupos_activos(activos: list[str]) -> set[str]:
    """Grupos con función (retinoides, AHA, vitamina C...) presentes en una lista de activos."""
    return {g for a in activos for g in grupos(a) if g in GRUPOS_ACTIVOS}


def irritacion(activos: list[str], sensible: bool = False, aclarado: bool = False) -> float:
    """Irritación de un producto en escala 0-2 (la del activo más irritante).

    El perfume solo suma en pieles sensibles. Los productos que se aclaran (limpiadores,
    champús) se quedan poco tiempo en la piel: cuentan la mitad.
    """
    base = max((IRRITACION.get(info(a).get("irritancy", "low"), 0)
                for a in activos if a != "fragrance"), default=0)
    if sensible and "fragrance" in activos:
        base = max(base, 1)
    return base * (0.5 if aclarado else 1.0)


def embarazo(activos: list[str]) -> str:
    """'avoid' si algún activo se desaconseja en embarazo, 'caution' si hay que consultarlo."""
    estados = {info(a).get("pregnancy_safe", "safe") for a in activos}
    return "avoid" if "avoid" in estados else "caution" if "caution" in estados else "safe"


# ---------------------------------------------------------------------------
# Matriz de compatibilidad (data/compatibilidad.json)
# ---------------------------------------------------------------------------
# Tipos de relación y cómo los trata el resto de la app:
#   evitar           -> no pueden ir en la misma rutina (el optimizador la descarta)
#   no_misma_sesion  -> noches alternas o uno de día y otro de noche
#   am_pm            -> se complementan, pero uno de día y otro de noche
#   precaucion       -> mejor separados mientras la piel se acostumbra
#   misma_clase      -> hacen lo mismo: con uno basta
#   sinergia         -> se potencian (el optimizador lo premia)
#   imprescindible   -> uno necesita al otro (retinoide -> protector solar)
SEPARAR = {"evitar", "no_misma_sesion", "am_pm", "precaucion", "misma_clase"}
GRAVEDAD_RELACION = {"evitar": "avoid", "no_misma_sesion": "caution", "am_pm": "caution",
                     "precaucion": "caution", "misma_clase": "caution"}


@lru_cache
def matriz() -> dict:
    datos = json.loads(COMPATIBILIDAD.read_text(encoding="utf-8"))
    por_id: dict[str, set[str]] = {}
    for fam, f in datos["familias"].items():
        for id_ in f["ids"]:
            por_id.setdefault(id_, set()).add(fam)
    pares: dict[frozenset, list[dict]] = {}
    for r in datos["relaciones"]:
        pares.setdefault(frozenset((r["a"], r["b"])), []).append(r)
    return {**datos, "por_id": por_id, "pares": pares}


def familias(activos) -> set[str]:
    """Familias de la matriz presentes en una lista de activos ("retinol" -> {"retinoides"})."""
    por_id = matriz()["por_id"]
    return {f for a in activos for f in por_id.get(a, ())}


def familia(nombre_familia: str) -> dict:
    return matriz()["familias"].get(nombre_familia, {})


def relaciones(activos_a, activos_b) -> list[dict]:
    """Todas las relaciones entre las familias de dos productos (o dos listas de activos)."""
    return list(_relaciones(tuple(sorted(activos_a)), tuple(sorted(activos_b))))


@lru_cache(maxsize=8192)
def _relaciones(activos_a: tuple, activos_b: tuple) -> tuple:
    fa, fb = familias(activos_a), familias(activos_b)
    pares, vistas, salida = matriz()["pares"], set(), []
    for x in fa:
        for y in fb:
            clave = frozenset((x, y))
            if clave in vistas:
                continue
            vistas.add(clave)
            for r in pares.get(clave, ()):
                # "misma clase" entre la MISMA familia solo cuenta si son dos productos distintos
                salida.append({**r, "titulo": matriz()["tipos"][r["tipo"]],
                               "nombre_a": familia(r["a"]).get("nombre", r["a"]),
                               "nombre_b": familia(r["b"]).get("nombre", r["b"])})
    return tuple(salida)


def sinergias(activos_a, activos_b) -> list[dict]:
    """Combinaciones que se potencian. Solo cuentan si al menos uno es un activo con función
    (que dos hidratantes "se lleven bien" no aporta nada que contar)."""
    return [r for r in relaciones(activos_a, activos_b) if r["tipo"] == "sinergia"
            and (familia(r["a"]).get("activo") or familia(r["b"]).get("activo"))]


def momento(activos) -> str:
    """'pm' si algún activo va solo de noche (retinoides, AHA), 'am' si solo de día (vitamina C pura)."""
    momentos = {familia(f).get("momento") for f in familias(activos) if f != "spf"}
    if "noche" in momentos:
        return "pm"
    if "manana" in momentos:
        return "am"
    return "ambos"


def conflictos(activos_a: list[str], activos_b: list[str]) -> list[dict]:
    """Relaciones que obligan a separar dos productos ('avoid' o 'caution'), con el porqué y el cómo."""
    return list(_conflictos(tuple(sorted(activos_a)), tuple(sorted(activos_b))))


@lru_cache(maxsize=4096)
def _conflictos(activos_a: tuple, activos_b: tuple) -> tuple:
    salida = []
    for r in _relaciones(activos_a, activos_b):
        if r["tipo"] not in SEPARAR:
            continue
        salida.append({**r, "severity": GRAVEDAD_RELACION[r["tipo"]],
                       "reason": r["porque"], "recommendation": r["como"]})
    # Lo más grave primero
    return tuple(sorted(salida, key=lambda r: r["severity"] != "avoid"))


def ids_desde_texto(textos: list[str]) -> set[str]:
    """Traduce lo que escribe el usuario ("perfume", "retinol", "lanolina") a ids de ingrediente."""
    sinonimos = {"perfume": "fragrance", "fragancia": "fragrance", "parfum": "fragrance",
                 "alcohol": "denatured-alcohol", "aceites esenciales": "tea-tree-oil",
                 "vitamina a": "retinol", "vitamina c": "ascorbic-acid", "aha": "glycolic-acid",
                 "bha": "salicylic-acid", "acido salicilico": "salicylic-acid",
                 "caracol": "snail-mucin", "coco": "coconut-oil", "lanolina": "lanolin",
                 "siliconas": "dimethicone", "urea": "urea", "propoleo": "propolis-extract",
                 "abeja": "propolis-extract", "miel": "honey", "centella": "centella-asiatica"}
    encontrados = set()
    for texto in textos:
        t = _plano(texto)
        if not t:
            continue
        if t in sinonimos:
            encontrados.add(sinonimos[t])
            continue
        for id_, i in _datos()[0].items():
            nombres = [id_, i.get("inci_name", ""), i.get("common_name", ""), i.get("nombre_es", ""),
                       *i.get("also_known_as", [])]
            if any(t == _plano(n) or (len(t) > 4 and t in _plano(n)) for n in nombres if n):
                encontrados.add(id_)
    # Evitar retinol implica evitar todos los retinoides (lo mismo con otros grupos)
    for id_ in list(encontrados):
        for g in grupos(id_) & {"retinoids", "aha", "bha", "vitamin_c_pure"}:
            encontrados |= {a for a, gs in _datos()[1].items() if g in gs}
    return encontrados


def ficha_texto(id_: str) -> str:
    """Texto de un ingrediente para el RAG."""
    i = info(id_)
    partes = [f"# {nombre(id_)} ({i.get('inci_name', id_)})", i.get("description", "")]
    if i.get("benefits"):
        partes.append("Beneficios: " + ", ".join(i["benefits"]))
    if i.get("skin_types"):
        partes.append("Tipos de piel: " + ", ".join(i["skin_types"]))
    partes.append(f"Irritación: {i.get('irritancy')}. Embarazo: {i.get('pregnancy_safe')}. "
                  f"Comedogenicidad (0-5): {i.get('comedogenic_rating')}. "
                  f"Momento: {i.get('time_of_use')}. Evidencia: {i.get('evidence_level')}.")
    if i.get("pairs_well_with"):
        partes.append("Combina bien con: " + ", ".join(i["pairs_well_with"]))
    if i.get("avoid_with"):
        partes.append("Evitar mezclar con: " + ", ".join(i["avoid_with"]))
    return "\n".join(p for p in partes if p)


def todos_los_ids() -> list[str]:
    return list(_datos()[0])


def encaje_tipo(p: dict, tipo: str) -> tuple[float, str]:
    """¿Le va bien este producto a este tipo de piel? Se juzga por lo que HACE, no por su etiqueta.

    Devuelve (penalización >= 0, consejo). La niacinamida "para piel grasa" va bien en piel seca si se
    sella con hidratación; lo que reseca de verdad es lo matificante, las espumas para piel grasa y los
    exfoliantes diarios. En piel grasa o con granitos, lo que molesta son las texturas ricas y lo comedogénico.
    """
    caracteristicas = set(p.get("caracteristicas", []))
    activos = p.get("activos", [])
    paso = p.get("paso", "")
    exfoliante = bool(grupos_activos(activos) & {"aha", "bha"}) and irritacion(activos) >= 1
    if tipo in ("seca", "atopica"):
        if "matificante" in caracteristicas:
            return 1.5, "matifica y puede resecar: úsalo solo donde tengas brillos"
        if paso == "limpiador" and "grasa" in p.get("objetivos", []):
            return 1.0, "es un limpiador para quitar grasa: si te deja tirante, cámbialo por uno en gel suave o crema"
        if exfoliante and paso not in ("limpiador", "limpiador_aceite"):
            return 0.5, "úsalo 2-3 noches por semana y sella con ácido hialurónico y ceramidas"
        if not any(t in p.get("apto_para", []) for t in ("todas", tipo)) and paso in ("serum", "esencia", "tratamiento", "tonico"):
            return 0.0, "va bien en piel seca si después aplicas un hidratante (hialurónico) y ceramidas"
        return 0.0, ""
    if tipo in ("grasa", "acneica", "mixta"):
        comedo = max((info(a).get("comedogenic_rating") or 0 for a in activos), default=0)
        if comedo >= 3:
            return 2.0, "lleva ingredientes que pueden taponar poros"
        if "textura_rica" in caracteristicas and paso not in ("limpiador", "limpiador_aceite"):
            return 1.0 if tipo == "mixta" else 1.5, "textura rica: puede taponar poros; úsala solo en zonas secas o de noche"
    return 0.0, ""
