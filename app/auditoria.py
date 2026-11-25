"""Revisor de rutina: la persona apunta la rutina que USA HOY y Dear Skin la revisa.

Entrada (lo que se rellena en la web, «Revisar mi rutina»):

    {"manana": [{"items": [{"id": "cerave-limpiador-espumoso", "dias": ["L","M","X","J","V","S","D"]}]}, ...],
     "noche":  [{"items": [{"id": "to-retinol-05", "dias": ["L","X","V"]},
                           {"id": "medicube-zero-pore-pad", "dias": ["M","J","S"]}]}, ...]}

Cada paso puede tener 1 o 2 productos que se alternan por días. Los ids son del catálogo
o del armario ("armario-7" para productos apuntados a mano).

Salida: nota, lo que está bien, problemas (con los días en que pasan), lo que sobra o aporta poco,
el orden correcto, alternativas mejores y una SEMANA PROPUESTA con sus propios productos
(noche de exfoliación, noche de retinoide, noches de recuperación: el "skin cycling").

Es determinista: el LLM solo lo explica con palabras.
"""

from app import catalogo, ingredientes
from app.rutina import ACLARADO, OBJETIVOS_ES, TOPE_IRRITACION

DIAS = ["L", "M", "X", "J", "V", "S", "D"]
NOMBRE_DIA = {"L": "lunes", "M": "martes", "X": "miércoles", "J": "jueves", "V": "viernes",
              "S": "sábado", "D": "domingo"}
MOMENTO_ES = {"manana": "mañana", "noche": "noche"}
# Orden de aplicación: de lo más ligero a lo más denso; el protector, siempre el último
ORDEN = ["limpiador_aceite", "limpiador", "tonico", "esencia", "serum", "tratamiento", "puntual",
         "contorno", "hidratante", "mascarilla", "spf"]
GRAVEDAD = {"alta": 15, "media": 7, "baja": 2}
CONSEJO_CONFLICTO = {
    "caution": "Úsalos en noches distintas (por ejemplo, ácido lunes y jueves, retinoide martes y viernes) "
               "y sella siempre con hidratante.",
    "avoid": "Juntos se anulan o irritan: sepáralos (uno por la mañana y otro por la noche, o en días distintos).",
}
BASE_SIN_OBJETIVO = {"limpiador_aceite", "limpiador", "hidratante", "spf"}


def _producto(id_: str, ctx: dict) -> dict | None:
    p = catalogo.producto_por_id(id_)
    if p:
        return p
    for item in ctx.get("armario", []):
        if id_ == f"armario-{item['id']}":
            return {"id": id_, "marca": "", "nombre": item["nombre"], "zona": item["zona"], "paso": item["paso"],
                    "momento": "ambos", "precio": None, "apto_para": ["todas"], "objetivos": item.get("objetivos") or [],
                    "caracteristicas": [], "activos": item.get("activos", []), "origen": ""}
    return None


def _nombre(p: dict) -> str:
    return f"{p['marca']} {p['nombre']}".strip()


def _dias_texto(dias: list[str]) -> str:
    dias = [d for d in DIAS if d in dias]
    if len(dias) == 7:
        return "todos los días"
    if not dias:
        return "ningún día"
    nombres = [NOMBRE_DIA[d] for d in dias]
    return ", ".join(nombres[:-1]) + (" y " if len(nombres) > 1 else "") + nombres[-1]


def _es_exfoliante(p: dict) -> bool:
    return (p["paso"] not in ACLARADO and bool(ingredientes.grupos_activos(p["activos"]) & {"aha", "bha", "pha"})
            and ingredientes.irritacion(p["activos"]) >= 1)


def _es_retinoide(p: dict) -> bool:
    return "retinoids" in ingredientes.grupos_activos(p["activos"]) and p["paso"] != "contorno"


def _es_recuperacion(p: dict) -> bool:
    objetivos = set(p["objetivos"])
    return ingredientes.irritacion(p["activos"]) == 0 and bool(objetivos & {"hidratacion", "calmar", "barrera", "rojeces"})


def analizar(rutina_usuario: dict, contexto: dict | None = None, necesidades: dict | None = None) -> dict:
    ctx = contexto or {}
    perfil = {**(ctx.get("perfil") or {}), **(necesidades or {})}
    tipo = perfil.get("tipo_piel") or ""
    sensible = bool(perfil.get("sensible"))
    objetivos = [o for o in list(dict.fromkeys((perfil.get("objetivos") or [])
                                                + catalogo.objetivos_de_deseos(perfil.get("deseos"))))
                 if o in OBJETIVOS_ES]
    if not objetivos:
        objetivos = ((ctx.get("ultima_rutina") or {}).get("necesidades") or {}).get("objetivos") or []
    evitar = ingredientes.ids_desde_texto(perfil.get("evitar") or [])
    # Objetivos implícitos: una piel sensible siempre agradece calmar; una seca, hidratar
    implicitos = set(objetivos) | ({"calmar", "rojeces", "barrera"} if sensible else set()) \
        | ({"hidratacion", "barrera"} if tipo in ("seca", "atopica") else set())
    reaccionados = set((ctx.get("journey") or {}).get("reaccionados", []))

    # 1. Expandir a "qué se pone cada día, mañana y noche"
    productos: dict[str, dict] = {}
    uso: dict[tuple[str, str], list[str]] = {(d, m): [] for d in DIAS for m in ("manana", "noche")}
    orden_usuario: dict[str, list[str]] = {"manana": [], "noche": []}
    desconocidos = []
    for momento in ("manana", "noche"):
        for paso in rutina_usuario.get(momento, []):
            for item in paso.get("items", []):
                p = _producto(item["id"], ctx)
                if not p:
                    desconocidos.append(item["id"])
                    continue
                productos[p["id"]] = p
                if p["id"] not in orden_usuario[momento]:
                    orden_usuario[momento].append(p["id"])
                for d in item.get("dias") or DIAS:
                    if d in DIAS:
                        uso[(d, momento)].append(p["id"])

    problemas: dict[str, dict] = {}   # clave -> problema (para agrupar el mismo problema en varios días)

    def problema(clave, gravedad, titulo, detalle, dia=None, producto=None):
        if clave not in problemas:
            problemas[clave] = {"gravedad": gravedad, "titulo": titulo, "detalle": detalle, "dias": [],
                                "producto": producto}
        if dia and dia not in problemas[clave]["dias"]:
            problemas[clave]["dias"].append(dia)

    bien = []
    sinergias_vistas: dict[frozenset, str] = {}
    sobran: dict[str, str] = {}
    a_cambiar: set[str] = set()

    # 2. Revisión de cada día y momento
    for (dia, momento), ids in uso.items():
        ps = [productos[i] for i in dict.fromkeys(ids)]
        # Conflictos entre activos
        for i, x in enumerate(ps):
            for y in ps[i + 1:]:
                if x["paso"] in ACLARADO or y["paso"] in ACLARADO:
                    continue          # un limpiador se aclara en segundos
                reglas = ingredientes.conflictos(x["activos"], y["activos"])
                for regla in reglas[:1]:
                    grav = "alta" if regla["severity"] == "avoid" else "baja" if regla["tipo"] == "misma_clase" else "media"
                    titulo = (f"{_nombre(x)} y {_nombre(y)} hacen lo mismo" if regla["tipo"] == "misma_clase"
                              else f"No juntes {_nombre(x)} y {_nombre(y)} la misma {MOMENTO_ES[momento]}")
                    problema(f"conflicto-{x['id']}-{y['id']}-{momento}", grav, titulo,
                             f"{regla['porque']} {regla['como']}", dia)
                if not reglas:
                    for regla in ingredientes.sinergias(x["activos"], y["activos"])[:1]:
                        sinergias_vistas.setdefault(frozenset((x["id"], y["id"])),
                                                    f"{_nombre(x)} + {_nombre(y)} se potencian: {regla['porque']}")
        # Saturación: demasiados activos a la vez
        carga = sum(ingredientes.irritacion(p["activos"], sensible, p["paso"] in ACLARADO) for p in ps)
        if carga > TOPE_IRRITACION[sensible]:
            fuertes = [_nombre(p) for p in ps if ingredientes.irritacion(p["activos"], sensible) >= 1]
            problema(f"carga-{momento}", "media", f"Saturas la piel algunas {MOMENTO_ES[momento]}s",
                     "Demasiados activos fuertes juntos (" + ", ".join(fuertes) + "). "
                     "Repártelos en días distintos y deja noches de descanso.", dia)
        # Retinoides de día y vitamina C pura de noche
        for p in ps:
            if momento == "manana" and (_es_retinoide(p) or p.get("momento") == "pm"):
                problema(f"manana-{p['id']}", "alta", f"Pasa {_nombre(p)} a la noche",
                         "Los retinoides y algunos activos se degradan con la luz y aumentan la "
                         "sensibilidad al sol: úsalos solo de noche.", dia, p["id"])
            if momento == "noche" and p["paso"] == "spf":
                problema(f"spf-noche-{p['id']}", "baja", "El protector solar de noche no hace falta",
                         "Guárdalo para la mañana.", dia, p["id"])
            if momento == "noche" and "vitamin_c_pure" in ingredientes.grupos_activos(p["activos"]):
                problema(f"vitc-{p['id']}", "baja", f"{_nombre(p)} rinde más por la mañana",
                         "La vitamina C es antioxidante: protege mejor de día, debajo del protector.", dia, p["id"])
        # Duplicados: dos productos de la misma familia de activos en la misma rutina
        for grupo in ingredientes.GRUPOS_ACTIVOS:
            con = [p for p in ps if grupo in ingredientes.grupos_activos(p["activos"]) and p["paso"] not in ACLARADO]
            if len(con) >= 2:
                problema(f"duplicado-{grupo}-{momento}", "baja",
                         f"Duplicas activos por la {MOMENTO_ES[momento]}",
                         " y ".join(_nombre(p) for p in con) + " llevan el mismo tipo de activo; con uno basta.", dia)
                sobran.setdefault(con[-1]["id"], f"repite el activo de {_nombre(con[0])}")
        hidratantes_ha = [p for p in ps if p["paso"] in ("serum", "esencia") and set(p["objetivos"]) <= {"hidratacion", "barrera", "calmar"}]
        if len(hidratantes_ha) >= 2:
            sobran.setdefault(hidratantes_ha[-1]["id"], f"hace lo mismo que {_nombre(hidratantes_ha[0])} (hidratar)")

    # 3. Revisión de la semana completa
    def dias_con(momento, cond):
        return [d for d in DIAS if any(cond(productos[i]) for i in uso[(d, momento)])]

    dias_spf = dias_con("manana", lambda p: p["paso"] == "spf")
    usa_activos = any(_es_retinoide(p) or _es_exfoliante(p) or
                      ingredientes.grupos_activos(p["activos"]) & {"vitamin_c_pure", "aha", "bha"}
                      for p in productos.values())
    if not dias_spf and orden_usuario["manana"]:
        problema("sin-spf", "alta", "Te falta protector solar por la mañana",
                 "Es el paso más importante: sin él, manchas y arrugas avanzan"
                 + (" y tus activos te hacen más sensible al sol." if usa_activos else "."))
    elif len(dias_spf) < 7 and orden_usuario["manana"]:
        problema("spf-algunos", "media", "Usa el protector solar todos los días",
                 f"Ahora solo lo usas {_dias_texto(dias_spf)}.")
    elif dias_spf:
        bien.append("Usas protector solar cada mañana.")

    if orden_usuario["noche"] and not dias_con("noche", lambda p: p["paso"] in ("limpiador", "limpiador_aceite")):
        problema("sin-limpiador", "media", "Límpiate la cara por la noche",
                 "Quitar protector, sebo y suciedad es lo que permite que el resto funcione.")
    else:
        if dias_con("noche", lambda p: p["paso"] == "limpiador_aceite"):
            bien.append("Haces doble limpieza por la noche: perfecto si usas protector o maquillaje.")
    for momento in ("manana", "noche"):
        if orden_usuario[momento] and len(dias_con(momento, lambda p: p["paso"] == "hidratante")) < 7:
            problema(f"sin-hidratante-{momento}", "media", f"Añade una hidratante por la {MOMENTO_ES[momento]}",
                     "Sella el agua en la piel y protege la barrera"
                     + (", sobre todo si usas activos." if usa_activos else "."))

    noches_retinoide = dias_con("noche", _es_retinoide)
    noches_exfoliante = dias_con("noche", _es_exfoliante)
    noches_fuertes = sorted(set(noches_retinoide) | set(noches_exfoliante), key=DIAS.index)
    if len(noches_retinoide) >= 6:
        problema("retinoide-diario", "media", "Usas el retinoide casi todas las noches",
                 "Si tu piel no está muy acostumbrada, 2-3 noches por semana dan resultado con menos "
                 "irritación. Las otras noches, recuperación.")
    if len(noches_exfoliante) >= 4:
        problema("exfoliante-diario", "media", "Exfolias demasiadas noches",
                 f"Ahora exfolias {_dias_texto(noches_exfoliante)}. Con 2-3 noches basta; más puede "
                 "dañar la barrera (rojez, tirantez, granitos).")
    if len(noches_fuertes) == 7:
        problema("sin-descanso", "media", "Tu piel no tiene ninguna noche de descanso",
                 "Deja al menos 2-3 noches solo con hidratación y calmantes para que la barrera se recupere.")
    elif noches_fuertes:
        bien.append(f"Dejas noches de descanso entre activos ({_dias_texto([d for d in DIAS if d not in noches_fuertes])}).")

    # Orden de aplicación
    orden_correcto = {}
    for momento, ids in orden_usuario.items():
        correcto = sorted(ids, key=lambda i: ORDEN.index(productos[i]["paso"]) if productos[i]["paso"] in ORDEN else 5)
        orden_correcto[momento] = [_nombre(productos[i]) for i in correcto]
        if ids and ids != correcto:
            problema(f"orden-{momento}", "baja", f"Cambia el orden de la {MOMENTO_ES[momento]}",
                     "De lo más ligero a lo más denso: " + " → ".join(orden_correcto[momento]) + ".")
    if all(not k.startswith("orden") for k in problemas) and any(orden_usuario.values()):
        bien.append("Aplicas los productos en buen orden.")

    # 4. Producto a producto: encaja con tu piel y tus objetivos
    cubiertos = set()
    for p in productos.values():
        nombre = _nombre(p)
        cubiertos |= set(p["objetivos"]) & set(objetivos)
        if p["id"] in reaccionados:
            problema(f"reaccion-{p['id']}", "alta", f"Según tu skin journey, {nombre} te sentó mal",
                     "Déjalo y vigila los productos con sus mismos activos.", producto=p["id"])
            a_cambiar.add(p["id"])
        if set(p["activos"]) & evitar:
            problema(f"evitar-{p['id']}", "alta", f"{nombre} lleva algo que quieres evitar",
                     ", ".join(ingredientes.nombre(a) for a in set(p["activos"]) & evitar) + ".", producto=p["id"])
            a_cambiar.add(p["id"])
        if perfil.get("embarazo") and ingredientes.embarazo(p["activos"]) == "avoid":
            problema(f"embarazo-{p['id']}", "alta", f"{nombre} no se recomienda en el embarazo",
                     "Consúltalo con tu médico o matrona.", producto=p["id"])
            a_cambiar.add(p["id"])
        if tipo:
            penalizacion, consejo = ingredientes.encaje_tipo(p, tipo)
            if penalizacion:
                problema(f"tipo-{p['id']}", "baja", f"Ojo con {nombre} en piel {tipo}", consejo[0].upper() + consejo[1:] + ".",
                         producto=p["id"])
            elif consejo:
                bien.append(f"{nombre}: {consejo}.")
        if sensible and "fragrance" in p["activos"] and p["paso"] not in ACLARADO:
            problema(f"perfume-{p['id']}", "baja", f"{nombre} lleva perfume",
                     "En piel sensible es de lo que más irrita.", producto=p["id"])
        if objetivos and p["paso"] not in BASE_SIN_OBJETIVO and p["objetivos"] and not set(p["objetivos"]) & implicitos:
            sobran.setdefault(p["id"], "no trabaja ninguno de tus objetivos ("
                              + ", ".join(OBJETIVOS_ES.get(o, o) for o in p["objetivos"][:3]) + ")")
        clave = [a for a in p["activos"] if a not in ingredientes.BASE]
        if clave and all(ingredientes.info(a).get("evidence_level") == "limited" for a in clave):
            sobran.setdefault(p["id"], "su ingrediente estrella (" + ", ".join(ingredientes.nombre(a) for a in clave[:2])
                              + ") tiene poca evidencia: más marketing que resultados")
    faltan = [o for o in objetivos if o not in cubiertos]

    # 5. Alternativas: para lo que hay que cambiar o aporta poco, y para objetivos sin cubrir
    alternativas = []
    tienen = set(productos)
    del_armario = {a["producto_id"] for a in ctx.get("armario", []) if a.get("producto_id")}

    def sugerir(paso, objetivo=None, excluir=()):
        lista = []
        for q in catalogo.cargar_productos():
            if (q["id"] in tienen or q["id"] in excluir or q["paso"] != paso or q["zona"] != "cara"
                    or (tipo and ingredientes.encaje_tipo(q, tipo)[0] >= 1) or set(q["activos"]) & evitar
                    or (sensible and (ingredientes.irritacion(q["activos"], True) >= 2 or "fragrance" in q["activos"]))
                    or (perfil.get("embarazo") and ingredientes.embarazo(q["activos"]) == "avoid")):
                continue
            puntos = len(set(q["objetivos"]) & set(objetivos)) * 2 + (objetivo in q["objetivos"]) * 3 \
                + (q["origen"] == "kr") * 0.5 - (q["precio"] or 30) / 60 + (q["id"] in del_armario) * 10
            lista.append((puntos, q))
        return [{**catalogo.resumen(q), "ya_lo_tienes": q["id"] in del_armario}
                for _, q in sorted(lista, key=lambda x: -x[0])[:2]]
    for pid in list(a_cambiar) + [i for i in sobran if i not in a_cambiar]:
        p = productos[pid]
        if p["paso"] in ORDEN:
            opciones = sugerir(p["paso"])
            if opciones:
                alternativas.append({"para": _nombre(p), "motivo": "cambiar" if pid in a_cambiar else "aporta poco",
                                     "opciones": opciones})
    # Lo imprescindible que falta: protector e hidratante
    if "sin-spf" in problemas or "spf-algunos" in problemas:
        opciones = sugerir("spf")
        if opciones:
            alternativas.insert(0, {"para": "el protector solar que te falta", "motivo": "imprescindible", "opciones": opciones})
    if any(k.startswith("sin-hidratante") for k in problemas):
        opciones = sugerir("hidratante")
        if opciones:
            alternativas.insert(0, {"para": "la hidratante que te falta", "motivo": "imprescindible", "opciones": opciones})
    for objetivo in faltan[:2]:
        opciones = sugerir("serum", objetivo)
        if opciones:
            alternativas.append({"para": f"tu objetivo «{OBJETIVOS_ES.get(objetivo, objetivo)}»",
                                 "motivo": "nadie lo trabaja", "opciones": opciones})

    # 6. Semana propuesta con SUS productos (skin cycling)
    semana = _semana_propuesta(productos, orden_usuario, sensible)

    lista_problemas = sorted(problemas.values(), key=lambda x: -GRAVEDAD[x["gravedad"]])
    for pr in lista_problemas:
        pr["cuando"] = _dias_texto(pr.pop("dias")) if pr.get("dias") else ""
    nota = max(10, 100 - sum(GRAVEDAD[pr["gravedad"]] for pr in lista_problemas) - 2 * len(sobran))
    if not lista_problemas:
        bien.append("No veo conflictos ni saturación: tu rutina está bien montada.")
    bien += list(sinergias_vistas.values())[:4]
    return {
        "nota": nota,
        "bien": bien,
        "problemas": lista_problemas,
        "sobran": [{"producto": _nombre(productos[i]), "id": i, "motivo": m} for i, m in sobran.items()],
        "objetivos_sin_cubrir": [OBJETIVOS_ES.get(o, o) for o in faltan],
        "orden_correcto": orden_correcto,
        "alternativas": alternativas,
        "semana_propuesta": semana,
        "desconocidos": desconocidos,
    }


def _semana_propuesta(productos: dict, orden: dict, sensible: bool) -> dict:
    """Reparte SUS productos en la semana: exfoliación, retinoide y recuperación ("skin cycling")."""
    def nombres(ids):
        return [_nombre(productos[i]) for i in sorted(dict.fromkeys(ids),
                key=lambda i: ORDEN.index(productos[i]["paso"]) if productos[i]["paso"] in ORDEN else 5)]

    noche = [productos[i] for i in orden["noche"]]
    manana = [productos[i] for i in orden["manana"]]
    base_noche = [p["id"] for p in noche if p["paso"] in ("limpiador_aceite", "limpiador", "hidratante", "contorno")]
    retinoides = [p["id"] for p in noche + manana if _es_retinoide(p)]
    exfoliantes = [p["id"] for p in noche + manana if _es_exfoliante(p)]
    recuperacion = [p["id"] for p in noche if _es_recuperacion(p) and p["paso"] not in ("hidratante",)]
    otros = [p["id"] for p in noche if p["id"] not in base_noche + retinoides + exfoliantes + recuperacion
             and p["paso"] not in ("spf",)]
    base_manana = [p["id"] for p in manana if not _es_retinoide(p) and not _es_exfoliante(p)]
    if not any(productos[i]["paso"] == "spf" for i in base_manana):
        base_manana.append("__spf__")
    falta_hidratante = not any(p["paso"] == "hidratante" for p in noche + manana)

    # Ciclo: exfoliación -> retinoide -> recuperación -> recuperación
    if retinoides and exfoliantes:
        plan = ["exfoliacion", "retinoide", "recuperacion", "recuperacion", "exfoliacion", "retinoide", "recuperacion"]
    elif retinoides:
        plan = (["retinoide", "recuperacion", "recuperacion", "retinoide", "recuperacion", "recuperacion", "recuperacion"]
                if sensible else
                ["retinoide", "recuperacion", "retinoide", "recuperacion", "retinoide", "recuperacion", "recuperacion"])
    elif exfoliantes:
        plan = ["exfoliacion", "recuperacion", "recuperacion", "exfoliacion", "recuperacion", "recuperacion", "recuperacion"]
    else:
        plan = ["tratamiento"] * 7
    etiquetas = {"exfoliacion": "Noche de exfoliación", "retinoide": "Noche de retinoide",
                 "recuperacion": "Noche de recuperación", "tratamiento": "Tu rutina de siempre"}
    dias = {}
    for dia, tipo_noche in zip(DIAS, plan):
        extra = {"exfoliacion": exfoliantes[:1], "retinoide": retinoides[:1],
                 "recuperacion": recuperacion + otros[:1], "tratamiento": recuperacion + otros}[tipo_noche]
        m = nombres([i for i in base_manana if i != "__spf__"])
        if "__spf__" in base_manana:
            m.append("Protector solar (te falta)")
        n = nombres(base_noche + extra)
        ids_m = [i for i in base_manana if i != "__spf__"]
        ids_n = list(dict.fromkeys(base_noche + extra))
        if falta_hidratante:
            m.insert(-1 if m and m[-1].startswith("Protector") else len(m), "Hidratante (te falta)")
            n.append("Hidratante (te falta)")
        dias[dia] = {"tipo": etiquetas[tipo_noche], "manana": m, "noche": n,
                     "ids": {"manana": ids_m, "noche": ids_n}}
    return {"dias": dias, "explicacion": (
        "Alterna activos y descanso: una noche exfolias, otra usas el retinoide y luego dejas que la piel "
        "se recupere con hidratación. Así ves resultados sin irritar la barrera."
        if retinoides or exfoliantes else
        "No usas activos fuertes, así que puedes repetir la misma rutina cada día.")}
