"""¿Merece la pena? (worth the hype)

El usuario escribe el nombre de un producto viral y Dear Skin le dice si merece la pena
incorporarlo a SU rutina:
  - si es compatible con su piel (tipo, sensibilidad, alergias, embarazo, reacciones previas),
  - si ya tiene algo equivalente en casa o en su rutina (mismos activos o misma función),
  - qué aportaría de nuevo (objetivos que su rutina no cubre),
  - si choca con algún activo que ya usa,
  - cuánta evidencia hay detrás de sus ingredientes estrella,
  - y si hay alternativas más baratas con los mismos activos.

Es un análisis determinista: el LLM solo lo explica.
"""

from app import catalogo, ingredientes
from app.rutina import OBJETIVOS_ES


def _productos_del_usuario(contexto: dict) -> list[dict]:
    """Lo que ya usa: armario + productos de su última rutina."""
    vistos, lista = set(), []
    for item in contexto.get("armario", []):
        p = catalogo.producto_por_id(item["producto_id"]) if item.get("producto_id") else None
        p = p or {"id": f"armario-{item['id']}", "marca": "", "nombre": item["nombre"], "paso": item["paso"],
                  "objetivos": [], "activos": item.get("activos", []), "precio": None}
        if p["id"] not in vistos:
            vistos.add(p["id"])
            lista.append(p)
    rutina = contexto.get("ultima_rutina") or {}
    for zona in rutina.get("zonas", {}).values():
        for seccion in zona.values():
            for paso in seccion:
                p = catalogo.producto_por_id(paso["producto"]["id"])
                if p and p["id"] not in vistos:
                    vistos.add(p["id"])
                    lista.append(p)
    return lista


def analizar(nombre_producto: str, contexto: dict | None = None) -> dict:
    ctx = contexto or {}
    perfil = ctx.get("perfil") or {}
    coincidencias = catalogo.buscar_texto(nombre_producto, limite=4)
    if not coincidencias or coincidencias[0][0] < 0.45:
        return {
            "encontrado": False, "consulta": nombre_producto,
            "sugerencias": [f"{p['marca']} {p['nombre']}" for _, p in coincidencias],
            "nota": "No está en el catálogo: puedo explicar sus ingredientes si me pasas la lista (INCI).",
        }
    p = coincidencias[0][1]
    tipo = perfil.get("tipo_pelo") if p["zona"] == "pelo" else perfil.get("tipo_piel")
    sensible = bool(perfil.get("sensible"))
    activos_clave = [a for a in p["activos"] if a not in ingredientes.BASE]

    # 1. Compatibilidad con su piel
    problemas, advertencias_tipo = [], None
    if tipo and p["zona"] == "cara":
        penalizacion, consejo = ingredientes.encaje_tipo(p, tipo)
        if penalizacion >= 1.5:
            problemas.append(consejo[0].upper() + consejo[1:] + ".")
        elif consejo:
            advertencias_tipo = consejo[0].upper() + consejo[1:] + "."
    elif tipo and not catalogo.apto(p, tipo):
        problemas.append(f"No está pensado para pelo {tipo}.")
    evitar = ingredientes.ids_desde_texto(perfil.get("evitar", []))
    if set(p["activos"]) & evitar:
        problemas.append("Lleva " + ", ".join(ingredientes.nombre(a) for a in set(p["activos"]) & evitar)
                         + ", que quieres evitar.")
    if perfil.get("embarazo") and ingredientes.embarazo(p["activos"]) == "avoid":
        problemas.append("Contiene activos que no se recomiendan en el embarazo.")
    irritacion = ingredientes.irritacion(p["activos"], sensible)
    if sensible and irritacion >= 2:
        problemas.append("Es bastante irritante para una piel sensible.")
    advertencias = [advertencias_tipo] if advertencias_tipo else []
    if sensible and irritacion >= 1 and irritacion < 2:
        advertencias.append("Puede picar en piel sensible: introdúcelo poco a poco.")
    if sensible and "fragrance" in p["activos"]:
        advertencias.append("Lleva perfume, que a veces irrita las pieles sensibles.")
    if perfil.get("embarazo") and ingredientes.embarazo(p["activos"]) == "caution":
        advertencias.append("En el embarazo, consulta este producto con tu médico.")
    journey = ctx.get("journey", {})
    if p["id"] in journey.get("reaccionados", []):
        problemas.append("Según tu skin journey, este producto ya te sentó mal.")

    # 2. ¿Ya tiene algo equivalente?
    suyos = [q for q in _productos_del_usuario(ctx) if q["id"] != p["id"]]
    equivalentes = []
    for q in suyos:
        comunes = set(activos_clave) & set(q["activos"])
        misma_funcion = (q["paso"] == p["paso"] and len(set(q["objetivos"]) & set(p["objetivos"])) >= 2)
        if comunes or misma_funcion:
            razon = ("comparten " + ", ".join(ingredientes.nombre(a) for a in comunes)) if comunes \
                else "hacen lo mismo en el mismo paso"
            equivalentes.append({"producto": f"{q['marca']} {q['nombre']}".strip(), "razon": razon})
    ya_tiene = p["id"] in {q["id"] for q in _productos_del_usuario(ctx)}

    # 3. ¿Qué aporta de nuevo?
    cubiertos = {o for q in suyos for o in q["objetivos"]}
    anteriores = ((ctx.get("ultima_rutina") or {}).get("necesidades") or {}).get("objetivos") or []
    objetivos_usuario = set(perfil.get("objetivos") or anteriores)
    aporta = [o for o in p["objetivos"] if o not in cubiertos]
    aporta_util = [o for o in aporta if not objetivos_usuario or o in objetivos_usuario]

    # 4. Conflictos con lo que ya usa
    conflictos = []
    for q in suyos:
        for regla in ingredientes.conflictos(p["activos"], q["activos"]):
            conflictos.append({"con": f"{q['marca']} {q['nombre']}".strip(), "gravedad": regla["severity"],
                               "consejo": regla["recommendation"]})

    # 5. Evidencia de sus ingredientes estrella
    evidencia = {ingredientes.nombre(a): ingredientes.info(a).get("evidence_level", "limited")
                 for a in activos_clave}
    poca_evidencia = bool(evidencia) and all(e == "limited" for e in evidencia.values())

    # 6. Alternativas más baratas con los mismos activos
    alternativas = []
    ids_suyos = {q["id"] for q in suyos}
    if p["precio"]:
        for q in catalogo.cargar_productos():
            if (q["id"] != p["id"] and q["id"] not in ids_suyos and q["paso"] == p["paso"] and q["precio"]
                    and q["precio"] <= 0.75 * p["precio"] and set(activos_clave) & set(q["activos"])
                    and (not tipo or catalogo.apto(q, tipo))):
                alternativas.append({"producto": f"{q['marca']} {q['nombre']}", "precio": q["precio"],
                                     "id": q["id"], "comparten": [ingredientes.nombre(a) for a in
                                                                  set(activos_clave) & set(q["activos"])]})
        alternativas.sort(key=lambda a: a["precio"])

    # Veredicto
    if problemas:
        veredicto = "no_para_ti"
    elif ya_tiene:
        veredicto = "ya_lo_tienes"
    elif equivalentes and not aporta_util:
        veredicto = "ya_tienes_algo_parecido"
    elif aporta_util and not poca_evidencia:
        veredicto = "merece_la_pena"
    else:
        veredicto = "opcional"
    textos = {
        "no_para_ti": "No te lo recomiendo para tu piel.",
        "ya_lo_tienes": "Ya lo tienes: no hace falta comprarlo otra vez.",
        "ya_tienes_algo_parecido": "Ya tienes algo que hace lo mismo: no lo necesitas.",
        "merece_la_pena": "Sí puede aportar algo a tu rutina.",
        "opcional": "Es un capricho opcional: no cubre nada que te falte o tiene poca evidencia.",
    }
    return {
        "encontrado": True,
        "producto": catalogo.resumen(p),
        "veredicto": veredicto,
        "veredicto_texto": textos[veredicto],
        "problemas": problemas,
        "advertencias": advertencias,
        "equivalentes": equivalentes,
        "aporta": [OBJETIVOS_ES.get(o, o) for o in aporta_util],
        "conflictos": conflictos,
        "evidencia": evidencia,
        "poca_evidencia": poca_evidencia,
        "alternativas_baratas": alternativas[:3],
    }
