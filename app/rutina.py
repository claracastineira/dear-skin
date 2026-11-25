"""Optimizador de rutinas: el "personal shopper" de Dear Skin.

No es un LLM: es un algoritmo determinista y explicable. El LLM traduce lo que dice
el usuario a unas Necesidades; este módulo calcula la mejor rutina posible.

Criterios que tiene en cuenta
-----------------------------
1. Compatibilidad con el tipo de piel/pelo         (filtro + puntuación)
2. Objetivos del usuario, por prioridad            (cobertura de objetivos de la combinación)
3. Presupuesto total                               (restricción; lo que ya tienes cuesta 0)
4. Ingredientes a evitar y embarazo                (filtro duro)
5. Irritación acumulada por rutina (mañana/noche)  (restricción, más estricta en piel sensible)
6. Conflictos entre activos (retinol + ácidos...)  ('avoid' -> descarta; 'caution' -> noches alternas)
7. Duplicidad (dos productos con el mismo activo)  (penalización)
8. Productos que ya tienes en casa (armario)       (coste 0 + prioridad)
9. Disponibilidad y precio en tiendas              (solo productos con precio si hay presupuesto)
10. Experiencias anteriores (skin journey)         (excluye lo que te sentó mal, premia lo que toleras)
11. Número máximo de pasos por rutina              (restricción)
Además: preferencia K-beauty, clima/viaje y reseñas de la comunidad.

Cómo optimiza
-------------
Para cada zona (cara, cuerpo, pelo) se eligen los mejores candidatos de cada "rol"
(limpiador, tónico, activo de mañana, activo de noche, hidratante, protector...) y se
prueban TODAS sus combinaciones (búsqueda exhaustiva sobre un espacio podado).
De cada zona se guarda la frontera de Pareto coste/puntuación y después se combinan
las zonas respetando el presupuesto total.
"""

import itertools
from dataclasses import asdict, dataclass, field, fields

from app import catalogo, ingredientes

OBJETIVOS_ES = {
    "acne": "granitos", "poros": "poros", "grasa": "exceso de grasa", "luminosidad": "luminosidad",
    "manchas": "manchas", "hidratacion": "hidratación", "calmar": "calmar", "rojeces": "rojeces",
    "barrera": "reparar la barrera", "antiedad": "antiedad", "textura": "textura",
    "ojeras": "ojeras", "limpieza": "limpieza", "proteccion_solar": "protección solar",
    "piel_aspera": "piel áspera", "granitos_cuerpo": "granitos en el cuerpo", "brillo": "brillo",
    "reparar": "reparar el pelo", "encrespamiento": "encrespamiento", "caspa": "caspa",
    "cuero_graso": "cuero cabelludo graso", "caida": "pelo débil", "volumen": "volumen",
    "hidratacion_pelo": "hidratación del pelo",
}
PESOS = [3.0, 2.2, 1.6, 1.2, 1.0, 0.8]     # peso de cada objetivo según su prioridad
TOPE_IRRITACION = {True: 2.0, False: 3.0}  # irritación máxima por rutina (sensible / no sensible)
ACLARADO = {"limpiador_aceite", "limpiador", "gel_corporal", "champu", "acondicionador",
            "mascarilla_capilar"}
# Cuánto "cuenta" un producto para cubrir un objetivo según su paso: un sérum trabaja más
# que un limpiador que se aclara a los 30 segundos o que el extracto de un protector solar.
POTENCIA = {"limpiador_aceite": 0.3, "limpiador": 0.4, "gel_corporal": 0.4, "champu": 0.6,
            "spf": 0.4, "hidratante": 0.7, "acondicionador": 0.8}


@dataclass
class Necesidades:
    """Lo que el usuario quiere. Lo rellena el LLM (o la web) y lo consume el optimizador."""

    zonas: list[str] = field(default_factory=lambda: ["cara"])
    tipo_piel: str = "normal"
    sensible: bool = False
    tipo_pelo: str = ""
    objetivos: list[str] = field(default_factory=list)          # por orden de prioridad
    presupuesto: float | None = None                            # € para lo que hay que comprar
    max_pasos: int = 4                                          # por rutina (mañana / noche)
    evitar_ingredientes: list[str] = field(default_factory=list)
    embarazo: bool = False
    clima: str = ""                                             # frio_seco | calor_humedo | sol_intenso
    preferencia_origen: str = "kbeauty"                         # kbeauty | indiferente
    ya_tengo: list[str] = field(default_factory=list)           # pasos que ya tiene (sin detalle)
    excluir_productos: list[str] = field(default_factory=list)  # no le gustan / no los quiere
    fijar_productos: list[str] = field(default_factory=list)    # quiere mantenerlos sí o sí
    fijar_roles: dict = field(default_factory=dict)             # {"activo_pm": id}: elegido en la web
    cambiar_por_similar: list[str] = field(default_factory=list)  # no le gusta ESTE, pero sí su función
    evitar_texturas: list[str] = field(default_factory=list)    # textura_oleosa, textura_rica...
    no_comedogenico: bool = False
    precio_max_producto: float | None = None
    deseos: list[str] = field(default_factory=list)             # "cómo quieres tu piel": glowy, mate...

    @classmethod
    def desde_dict(cls, datos: dict) -> "Necesidades":
        validos = {f.name for f in fields(cls)}
        n = cls(**{k: v for k, v in (datos or {}).items() if k in validos and v is not None})
        n.zonas = [catalogo.normalizar(z) for z in n.zonas if catalogo.normalizar(z) in catalogo.OBJETIVOS] or ["cara"]
        n.objetivos = list(dict.fromkeys(catalogo.normalizar(o) for o in n.objetivos))
        n.tipo_piel = catalogo.normalizar(n.tipo_piel or "normal")
        if n.tipo_piel == "sensible":          # "sensible" es una condición, no un tipo
            n.sensible, n.tipo_piel = True, "normal"
        n.tipo_pelo = catalogo.normalizar(n.tipo_pelo) if n.tipo_pelo else ""
        n.max_pasos = max(2, min(int(n.max_pasos or 4), 10))
        # Los deseos generales ("glowy", "smooth") se suman a los objetivos, detrás de los concretos
        n.deseos = [d for d in n.deseos if d in catalogo.DESEOS]
        n.objetivos = list(dict.fromkeys(n.objetivos + catalogo.objetivos_de_deseos(n.deseos)))
        # Palabras de textura que el LLM a veces mete como "ingredientes a evitar"
        TEXTURAS = {"aceite": "textura_oleosa", "aceitoso": "textura_oleosa", "aceitosa": "textura_oleosa",
                    "oleoso": "textura_oleosa", "graso": "textura_oleosa", "grasiento": "textura_oleosa",
                    "pegajoso": "textura_rica", "pesado": "textura_rica", "denso": "textura_rica"}
        ingredientes_reales = []
        for texto in n.evitar_ingredientes:
            plano = catalogo._plano(texto)
            if plano in TEXTURAS:
                n.evitar_texturas.append(TEXTURAS[plano])
            elif "comedogen" in plano:
                n.no_comedogenico = True
            else:
                ingredientes_reales.append(texto)
        n.evitar_ingredientes = ingredientes_reales
        n.evitar_texturas = list(dict.fromkeys(catalogo.normalizar(t) if not t.startswith("textura_") else t
                                               for t in n.evitar_texturas))
        n.excluir_productos = list(dict.fromkeys(n.excluir_productos + n.cambiar_por_similar))
        # Si ahora no quiere un producto que antes eligió, deja de estar fijado
        n.fijar_roles = {r: i for r, i in (n.fijar_roles or {}).items() if i not in n.excluir_productos}
        n.fijar_productos = [i for i in n.fijar_productos if i not in n.excluir_productos]
        return n


@dataclass(frozen=True)
class Rol:
    nombre: str
    pasos: frozenset
    obligatorio: bool


ROLES = {
    "cara": [
        Rol("limpiador_aceite", frozenset({"limpiador_aceite"}), False),
        Rol("limpiador", frozenset({"limpiador"}), True),
        Rol("tonico", frozenset({"tonico", "esencia"}), False),
        Rol("activo_am", frozenset({"serum", "esencia", "tratamiento"}), False),
        Rol("activo_pm", frozenset({"serum", "esencia", "tratamiento"}), False),
        Rol("hidratante", frozenset({"hidratante"}), True),
        Rol("spf", frozenset({"spf"}), True),
    ],
    "cuerpo": [
        Rol("gel_corporal", frozenset({"gel_corporal"}), False),
        Rol("hidratante_corporal", frozenset({"hidratante_corporal"}), True),
        Rol("tratamiento_corporal", frozenset({"tratamiento_corporal"}), False),
    ],
    "pelo": [
        Rol("champu", frozenset({"champu"}), True),
        Rol("acondicionador", frozenset({"acondicionador", "mascarilla_capilar"}), False),
        Rol("tratamiento_capilar", frozenset({"tratamiento_capilar"}), False),
        Rol("cuero_cabelludo", frozenset({"cuero_cabelludo"}), False),
    ],
}
# Sérum hidratante que va encima del activo (o solo, por la mañana) para compensarlo: hialurónico,
# ceramidas, centella... Sin activos que irriten, así que se puede juntar con cualquier tratamiento.
# No entra en la búsqueda exhaustiva (la haría 5 veces más lenta): se añade después a las mejores
# rutinas si cabe en los pasos y en el presupuesto y de verdad aporta.
CAPA = Rol("capa_hidratante", frozenset({"serum", "esencia"}), False)

NOMBRE_ROL = {
    "limpiador_aceite": "Limpiador en aceite (doble limpieza)", "limpiador": "Limpiador",
    "tonico": "Tónico / esencia", "activo_am": "Sérum de mañana", "activo_pm": "Tratamiento de noche",
    "activo_pm_alt": "Las otras noches",
    "capa_hidratante": "Sérum hidratante (compensa el activo)",
    "hidratante": "Hidratante", "spf": "Protector solar", "gel_corporal": "Gel de ducha",
    "hidratante_corporal": "Hidratante corporal", "tratamiento_corporal": "Tratamiento corporal",
    "champu": "Champú", "acondicionador": "Acondicionador / mascarilla",
    "tratamiento_capilar": "Sérum o aceite capilar", "cuero_cabelludo": "Cuero cabelludo",
}
PASOS_SINONIMOS = {
    "crema": "hidratante", "hidratante": "hidratante", "crema hidratante": "hidratante",
    "protector": "spf", "protector solar": "spf", "crema solar": "spf", "solar": "spf", "spf": "spf",
    "limpiador": "limpiador", "gel limpiador": "limpiador", "espuma": "limpiador",
    "aceite limpiador": "limpiador_aceite", "balsamo limpiador": "limpiador_aceite",
    "desmaquillante": "limpiador_aceite", "tonico": "tonico", "esencia": "esencia",
    "serum": "serum", "champu": "champu", "acondicionador": "acondicionador",
    "mascarilla capilar": "mascarilla_capilar", "aceite capilar": "tratamiento_capilar",
    "gel de ducha": "gel_corporal", "crema corporal": "hidratante_corporal",
    "locion corporal": "hidratante_corporal", "hidratante corporal": "hidratante_corporal",
}


def normalizar_paso(texto: str) -> str:
    plano = catalogo._plano(texto)
    return PASOS_SINONIMOS.get(plano, plano.replace(" ", "_"))


SECCIONES = {"cara": ("manana", "noche"), "cuerpo": ("ducha", "despues"), "pelo": ("lavado", "acabado")}


@dataclass
class Candidato:
    p: dict
    propio: bool          # ya lo tiene en casa
    coste: float          # lo que hay que pagar (0 si es propio)
    ajuste: float         # puntuación sin contar objetivos
    objetivos: frozenset
    irritacion: float
    grupos: frozenset     # grupos de activos con función (retinoides, AHA...)
    motivos: list[str]
    activos: tuple = ()

    @property
    def id(self) -> str:
        return self.p["id"]


# ---------------------------------------------------------------------------
# 1. Candidatos
# ---------------------------------------------------------------------------

def _objetivos_zona(n: Necesidades, zona: str) -> list[str]:
    return [o for o in n.objetivos if o in catalogo.OBJETIVOS[zona]]


def _pesos(objetivos: list[str]) -> dict[str, float]:
    return {o: PESOS[min(i, len(PESOS) - 1)] for i, o in enumerate(objetivos)}


def _opiniones(producto_id: str, tipo: str, opiniones: dict | None) -> dict:
    return (opiniones or {}).get(producto_id, {"total": 0})


def _motivo_descarte(p: dict, n: Necesidades, tipo: str, evitar: set, excluidos: set) -> str | None:
    """Filtros duros. Devuelve el motivo si el producto no vale para esta persona."""
    if p["id"] in excluidos:
        return "lo has descartado o te sentó mal"
    if p["paso"] not in ACLARADO and set(p["caracteristicas"]) & set(n.evitar_texturas):
        return "tiene una textura que no te gusta (" + ", ".join(
            t.replace("textura_", "") for t in set(p["caracteristicas"]) & set(n.evitar_texturas)) + ")"
    if set(p["activos"]) & evitar:
        comunes = ", ".join(ingredientes.nombre(a) for a in set(p["activos"]) & evitar)
        return f"lleva {comunes}, que quieres evitar"
    if n.embarazo and ingredientes.embarazo(p["activos"]) == "avoid":
        return "no se recomienda durante el embarazo"
    if n.presupuesto is not None and p["precio"] is None:
        return "no tenemos su precio"
    if n.precio_max_producto and (p["precio"] or 0) > n.precio_max_producto:
        return f"cuesta más de {n.precio_max_producto:.0f} €"
    return None


def _ajuste(p: dict, n: Necesidades, tipo: str, propio: bool, journey: dict,
            sospechosos: set, opiniones: dict | None, similar: dict | None = None) -> tuple[float, list[str]]:
    """Puntuación de "lo bien que encaja" un producto, sin contar los objetivos."""
    s, motivos = 1.0, []
    # Sustituto de un producto que no le gustó: mismo tipo de activo, otra textura/marca
    for original, (grupos_orig, paso_orig, objetivos_orig) in (similar or {}).items():
        mis_grupos = ingredientes.grupos_activos(p["activos"])
        if grupos_orig and mis_grupos & grupos_orig:
            s += 7.0          # lo ha pedido expresamente: tiene prioridad sobre lo que ya tiene
            motivos.append(f"Alternativa a {original} con el mismo tipo de activo")
        elif p["paso"] == paso_orig and len(set(p["objetivos"]) & objetivos_orig) >= 2:
            s += 1.5
            motivos.append(f"Hace una función parecida a {original}")
    if propio:
        s += 4.0          # usar lo que ya tienes casi siempre es lo mejor (y no cuesta nada)
        motivos.append("Ya lo tienes en casa")
    if tipo and tipo in p["apto_para"]:
        s += 0.75
        motivos.append(f"Pensado para {'piel' if p['zona'] != 'pelo' else 'pelo'} {tipo}")
    if tipo and p["zona"] == "cara":
        # Se juzga por lo que hace el producto, no por su etiqueta "para piel X"
        penalizacion, consejo = ingredientes.encaje_tipo(p, tipo)
        s -= penalizacion
        if consejo and (penalizacion or propio):
            motivos.append(consejo[0].upper() + consejo[1:])
    if n.sensible:
        if "sensible" in p["apto_para"]:
            s += 0.75
            motivos.append("Apto para piel sensible")
        if "fragrance" in p["activos"]:
            s -= 2
        elif "sin_perfume" in p["caracteristicas"]:
            s += 0.5
            motivos.append("Sin perfume")
    irr = ingredientes.irritacion(p["activos"], n.sensible, p["paso"] in ACLARADO)
    s -= irr * (1.5 if n.sensible else 0.5)

    # Comedogenicidad para pieles grasas o con granitos
    if p["zona"] == "cara" and (tipo in ("grasa", "acneica") or {"acne", "poros"} & set(n.objetivos) or n.no_comedogenico):
        comedo = max((ingredientes.info(a).get("comedogenic_rating") or 0 for a in p["activos"]), default=0)
        s -= 2 if comedo >= 3 else 0.5 if comedo == 2 else 0
        if "no_comedogenico" in p["caracteristicas"]:
            s += 0.5
            motivos.append("No comedogénico")

    if n.embarazo and ingredientes.embarazo(p["activos"]) == "caution":
        s -= 1
    if p.get("fuente") not in (None, "curado"):
        s -= 0.5          # importado: ingredientes deducidos del nombre, menos fiable
    if n.preferencia_origen == "kbeauty" and p.get("origen") == "kr":
        s += 0.75
        motivos.append("K-beauty")

    # Clima o viaje
    caracteristicas = set(p["caracteristicas"])
    if n.clima == "frio_seco" and p["paso"] in ("hidratante", "hidratante_corporal"):
        if "textura_rica" in caracteristicas or "barrera" in p["objetivos"]:
            s += 1.5
            motivos.append("Textura nutritiva para el frío")
        elif "textura_ligera" in caracteristicas:
            s -= 0.75
    if n.clima == "frio_seco" and ingredientes.grupos_activos(p["activos"]) & {"aha", "bha", "retinoids"}:
        s -= 1
    if n.clima == "calor_humedo" and p["zona"] == "cara":
        if "textura_ligera" in caracteristicas:
            s += 1
            motivos.append("Textura ligera para el calor")
        elif "textura_rica" in caracteristicas:
            s -= 1
    if n.clima == "sol_intenso" and p["paso"] == "spf":
        s += 0.5

    # Acabado que quiere: glowy/dewy (jugoso) o mate / fresco (ligero)
    acabados = catalogo.acabados_de_deseos(n.deseos)
    if p["zona"] == "cara" and p["paso"] not in ACLARADO and acabados:
        if "jugoso" in acabados:
            if "matificante" in caracteristicas:
                s -= 1.0
            elif "luminosidad" in p["objetivos"] or "aporta_brillo" in caracteristicas:
                s += 0.4
                motivos.append("Acabado jugoso, como lo quieres")
        if acabados & {"mate", "ligero"}:
            if "textura_rica" in caracteristicas:
                s -= 0.75
            elif "textura_ligera" in caracteristicas or "matificante" in caracteristicas:
                s += 0.4
                motivos.append("Textura ligera" + (" y acabado mate" if "mate" in acabados else ""))

    # Skin journey: lo que toleraste bien suma, lo que se parece a lo que te sentó mal resta
    if p["id"] in journey.get("bien_tolerados", []):
        s += 1.5
        motivos.append("Lo toleraste bien en tu skin journey")
    compartidos = set(p["activos"]) & sospechosos
    if compartidos:
        s -= min(3, 1.5 * len(compartidos))

    # Reseñas de la comunidad
    op = _opiniones(p["id"], tipo, opiniones)
    if op.get("total", 0) >= 3 and op.get("media"):
        s += (op["media"] - 3) * 0.5
        texto = f"★{op['media']} en {op['total']} reseñas"
        largo = op.get("largo_plazo") or {}
        if largo.get("total", 0) >= 2 and largo.get("media"):
            texto += f" ({largo['media']} tras 8+ semanas)"
            s += 0.3 if largo["media"] >= 4 else 0
        motivos.append(texto)
        mi_tipo = op.get("tu_tipo_de_piel") or {}
        if mi_tipo.get("total", 0) >= 2 and mi_tipo.get("reacciones", 0) / mi_tipo["total"] > 0.3:
            s -= 1

    # Precio (desempate suave)
    if not propio and p["precio"]:
        s -= p["precio"] / n.presupuesto if n.presupuesto else p["precio"] / 100
    return s, motivos


def _propios(ctx: dict, n: Necesidades) -> list[dict]:
    """Productos del armario (y los "ya tengo" genéricos) como pseudo-productos."""
    lista, vistos = [], set()
    momentos = {"manana": "am", "noche": "pm"}
    for item in ctx.get("armario", []):
        base = catalogo.producto_por_id(item["producto_id"]) if item.get("producto_id") else None
        if base and base["id"] in vistos:          # el mismo producto apuntado dos veces
            continue
        if base:
            vistos.add(base["id"])
            p = {**base, "_armario": item["id"]}
            # Si la persona dice que lo usa de mañana o de noche, se respeta
            if item.get("momento") in momentos:
                p["momento"] = momentos[item["momento"]]
            lista.append(p)
        else:
            lista.append({
                "id": f"armario-{item['id']}", "marca": "", "nombre": item["nombre"], "origen": "",
                "zona": item["zona"], "paso": item["paso"],
                "momento": momentos.get(item.get("momento"), "ambos"), "precio": 0.0,
                "tamano": "", "apto_para": ["todas"], "objetivos": item.get("objetivos") or [], "caracteristicas": [],
                "activos": item.get("activos", []), "tiendas": [], "descripcion": "Producto de tu armario.",
                "_armario": item["id"],
            })
    tienen = {p["paso"] for p in lista}
    for paso in n.ya_tengo:
        paso = normalizar_paso(paso)
        if paso in tienen:
            continue
        zona = next((z for z, roles in ROLES.items() for r in roles if paso in r.pasos), "cara")
        lista.append({
            "id": f"propio-{paso}", "marca": "", "nombre": f"Tu {paso.replace('_', ' ')} actual",
            "origen": "", "zona": zona, "paso": paso, "momento": "ambos", "precio": 0.0, "tamano": "",
            "apto_para": ["todas"], "objetivos": [], "caracteristicas": [], "activos": [],
            "tiendas": [], "descripcion": "El que ya usas.", "_armario": None,
        })
    return lista


def _candidatos(n: Necesidades, ctx: dict, opiniones: dict | None) -> tuple[dict, dict, list[dict], list[str]]:
    """Candidatos por zona y rol, más los descartes relevantes y avisos."""
    perfil_journey = ctx.get("journey", {})
    reaccionados = set(perfil_journey.get("reaccionados", []))
    # Los registros del diario pueden apuntar al armario ("armario-3"): los traducimos al catálogo
    for item in ctx.get("armario", []):
        if f"armario-{item['id']}" in reaccionados and item.get("producto_id"):
            reaccionados.add(item["producto_id"])
    sospechosos = set()
    for pid in reaccionados:
        p = catalogo.producto_por_id(pid)
        if p:
            sospechosos |= {a for a in p["activos"] if a not in ingredientes.BASE
                            and (ingredientes.info(a).get("irritancy") != "low" or ingredientes.grupos(a))}
    evitar = ingredientes.ids_desde_texto(n.evitar_ingredientes)
    excluidos = set(n.excluir_productos) | reaccionados
    similar = {}
    for pid in n.cambiar_por_similar:
        q = catalogo.producto_por_id(pid)
        if q:
            similar[f"{q['marca']} {q['nombre']}"] = (ingredientes.grupos_activos(q["activos"]) - {"niacinamide"},
                                                      q["paso"], set(q["objetivos"]))
    propios = _propios(ctx, n)
    ids_propios = {p["id"] for p in propios}

    candidatos: dict[str, dict[str, list[Candidato]]] = {}
    alternativas: dict[str, dict[str, list[Candidato]]] = {}
    descartes, avisos = [], []
    for zona in n.zonas:
        alternativas[zona] = {}
        tipo = n.tipo_pelo if zona == "pelo" else n.tipo_piel
        pesos = _pesos(_objetivos_zona(n, zona))
        candidatos[zona] = {}
        for rol in ROLES[zona] + ([CAPA] if zona == "cara" else []):
            lista = []
            fuente = [(p, True) for p in propios if p["zona"] == zona and p["paso"] in rol.pasos]
            fuente += [(p, False) for p in catalogo.cargar_productos()
                       if p["zona"] == zona and p["paso"] in rol.pasos and p["id"] not in ids_propios]
            for p, propio in fuente:
                momento = p.get("momento", "ambos")
                if (rol.nombre == "activo_am" and momento == "pm") or \
                        (rol.nombre in ("activo_pm", "activo_pm_alt") and momento == "am"):
                    continue
                es_capa = (ingredientes.irritacion(p["activos"]) == 0 and not ingredientes.grupos_activos(p["activos"])
                           and bool(set(p["objetivos"]) & {"hidratacion", "barrera", "calmar"}))
                if rol.nombre == "capa_hidratante" and not es_capa:
                    continue
                # El hueco del tratamiento (mañana y noche) es para un activo; el hidratante va encima (capa)
                if rol.nombre in ("activo_am", "activo_pm") and zona == "cara" and es_capa:
                    continue
                motivo = None if p["id"].startswith(("armario-", "propio-")) else \
                    _motivo_descarte(p, n, tipo, evitar, excluidos)
                if motivo:
                    relevantes = set(p["objetivos"]) & set(pesos)
                    if propio:
                        avisos.append(f"No uso tu {p['marca']} {p['nombre']}: {motivo}.")
                    elif relevantes:
                        descartes.append({"producto": f"{p['marca']} {p['nombre']}", "motivo": motivo,
                                          "relevancia": sum(pesos[o] for o in relevantes)})
                    continue
                ajuste, motivos = _ajuste(p, n, tipo, propio, perfil_journey, sospechosos, opiniones, similar)
                coste = 0.0 if propio else (p["precio"] if p["precio"] is not None else 25.0)
                lista.append(Candidato(
                    p=p, propio=propio, coste=coste, ajuste=ajuste,
                    objetivos=frozenset(o for o in p["objetivos"] if o in pesos),
                    irritacion=ingredientes.irritacion(p["activos"], n.sensible, p["paso"] in ACLARADO),
                    grupos=frozenset(ingredientes.grupos_activos(p["activos"])), motivos=motivos,
                    activos=tuple(sorted(p["activos"])),
                ))
            # Si ya tienes algo para este paso, comprar otro tiene que merecer mucho la pena
            if any(c.propio for c in lista):
                for c in lista:
                    if not c.propio:
                        c.ajuste -= 1.0
            fijos = [n.fijar_roles[rol.nombre]] if rol.nombre in n.fijar_roles else n.fijar_productos
            # "Cámbiame esto por algo parecido": en el paso donde iba, solo valen sustitutos del mismo tipo
            sustitutos = [c for c in lista if any(g and set(c.grupos) & g for g, paso_o, _ in similar.values())]
            if sustitutos and rol.nombre not in n.fijar_roles and any(paso_o in rol.pasos for _, paso_o, _ in similar.values()):
                fijos = [c.id for c in sorted(sustitutos, key=lambda c: -c.ajuste)[:3]]
            candidatos[zona][rol.nombre] = _podar(lista, pesos, fijos, rol.obligatorio)
            if rol.nombre == "capa_hidratante" and rol.nombre not in n.fijar_roles:
                orden = sorted(candidatos[zona][rol.nombre], key=lambda c: -(c.ajuste + sum(pesos[o] for o in c.objetivos)))
                candidatos[zona][rol.nombre] = [c for c in orden if c.propio][:2] + [c for c in orden if not c.propio][:2]
            # Todas las opciones compatibles, para ofrecer alternativas en cada paso
            alternativas[zona][rol.nombre] = sorted(
                lista, key=lambda c: -(c.ajuste + sum(pesos[o] for o in c.objetivos)))[:8]
    descartes.sort(key=lambda d: -d["relevancia"])
    vistos, unicos = set(), []
    for d in descartes:                      # un mismo producto puede salir en dos roles
        if d["producto"] not in vistos:
            vistos.add(d["producto"])
            unicos.append({"producto": d["producto"], "motivo": d["motivo"]})
    return candidatos, alternativas, unicos[:6], list(dict.fromkeys(avisos))


def _podar(lista: list[Candidato], pesos: dict, fijar: list[str], obligatorio: bool) -> list[Candidato]:
    """Se queda con los mejores de cada rol para que la búsqueda exhaustiva sea rápida."""
    fijados = [c for c in lista if c.id in fijar]
    if fijados:
        return fijados
    def valor(c):
        return c.ajuste + sum(pesos[o] for o in c.objetivos)
    mejores = sorted(lista, key=valor, reverse=True)
    propios = sorted((c for c in lista if c.propio), key=valor, reverse=True)[:3]
    elegidos = [c for c in mejores if not c.propio][:3] + propios
    if obligatorio:                                   # para que siempre haya opciones baratas
        elegidos += sorted(lista, key=lambda c: c.coste)[:2]
    unicos = {}
    for c in elegidos:
        unicos.setdefault(c.id, c)
    return list(unicos.values())


# ---------------------------------------------------------------------------
# 2. Evaluación de una combinación
# ---------------------------------------------------------------------------

def _colocar(zona: str, sel: dict, max_pasos: int) -> dict | None:
    """Coloca los productos elegidos en mañana/noche (o ducha/después, lavado/acabado).

    Devuelve None si no caben en el número máximo de pasos.
    """
    if zona != "cara":
        elegidos = [r.nombre for r in ROLES[zona] if sel.get(r.nombre)]
        if len(elegidos) > max_pasos:
            return None
        a, b = SECCIONES[zona]
        primera = {"cuerpo": {"gel_corporal"}, "pelo": {"champu", "acondicionador"}}[zona]
        return {a: [r for r in elegidos if r in primera], b: [r for r in elegidos if r not in primera]}

    manana = [r for r in ("activo_am", "hidratante", "spf") if sel.get(r)]
    noche = [r for r in ("limpiador_aceite", "limpiador", "activo_pm", "hidratante") if sel.get(r)]
    if len(manana) > max_pasos or len(noche) > max_pasos:
        return None
    tonico = sel.get("tonico")
    if tonico:
        momento = tonico.p.get("momento", "ambos")
        colocado = False
        if momento != "am" and len(noche) < max_pasos:
            noche.insert(noche.index("limpiador") + 1, "tonico")
            colocado = True
        # Por la mañana, el limpiador va antes que el tónico
        if len(manana) < max_pasos:
            manana.insert(0, "limpiador")
        if momento != "pm" and len(manana) < max_pasos:
            manana.insert(manana.index("limpiador") + 1 if "limpiador" in manana else 0, "tonico")
            colocado = True
        if not colocado:
            return None
    elif len(manana) < max_pasos:
        manana.insert(0, "limpiador")
    capa = sel.get("capa_hidratante")
    if capa:
        colocada = False
        if capa.p.get("momento", "ambos") != "am" and len(noche) < max_pasos:
            noche.insert(noche.index("hidratante"), "capa_hidratante")
            colocada = True
        if capa.p.get("momento", "ambos") != "pm" and len(manana) < max_pasos:
            manana.insert(manana.index("hidratante"), "capa_hidratante")
            colocada = True
        if not colocada:
            return None
    return {"manana": manana, "noche": noche}


def _evaluar(zona: str, sel: dict, n: Necesidades, pesos: dict) -> dict | None:
    secciones = _colocar(zona, sel, n.max_pasos)
    if secciones is None:
        return None

    # Irritación acumulada y conflictos dentro de cada rutina
    alternas, penalizacion, sinergias = [], 0.0, {}
    for nombre_seccion, roles in secciones.items():
        cands = list({sel[r].id: sel[r] for r in roles}.values())
        carga = sum(c.irritacion for c in cands)
        for x, y in itertools.combinations(cands, 2):
            reglas = ingredientes._conflictos(x.activos, y.activos)
            if any(r["severity"] == "avoid" for r in reglas):
                return None
            if reglas and (x.p["paso"] in ACLARADO or y.p["paso"] in ACLARADO):
                continue  # un limpiador se aclara en segundos: no hace falta alternarlo
            if reglas:   # 'caution': se usan en días alternos, así que no se suman
                alternas.append((x.id, y.id, reglas[0]["recommendation"]))
                carga -= min(x.irritacion, y.irritacion)
                penalizacion += 0.3
            elif x.p["paso"] not in ACLARADO and y.p["paso"] not in ACLARADO:
                for r in ingredientes.sinergias(x.activos, y.activos):   # se potencian
                    sinergias.setdefault((x.id, y.id), r)
        if carga > TOPE_IRRITACION[n.sensible]:
            return None

    distintos = list({c.id: c for c in sel.values() if c}.values())
    coste = sum(c.coste for c in distintos)   # el presupuesto se aplica al combinar zonas

    # Cobertura de objetivos: cubrir cada objetivo una vez vale mucho, repetirlo poco
    puntos = sum(c.ajuste for c in distintos)
    for objetivo, peso in pesos.items():
        fuerza = sum(POTENCIA.get(c.p["paso"], 1.0) for c in distintos if objetivo in c.objetivos)
        puntos += peso * min(1.0, fuerza) + 0.25 * peso * (fuerza >= 1.8)
    # Duplicidad: dos productos distintos con la misma familia de activos
    for grupo in ingredientes.GRUPOS_ACTIVOS:
        veces = sum(grupo in c.grupos for c in distintos)
        if veces >= 2:
            penalizacion += (0.75 if grupo == "niacinamide" else 1.5) * (veces - 1)
    puntos += min(1.2, 0.3 * len(sinergias))      # combinaciones que se potencian (matriz de compatibilidad)
    return {"puntos": puntos - penalizacion, "coste": coste, "sel": sel,
            "secciones": secciones, "alternas": alternas, "sinergias": sinergias}


def _optimizar_zona(zona: str, candidatos: dict, n: Necesidades) -> list[dict]:
    """Búsqueda exhaustiva. Devuelve la frontera de Pareto (más barato <-> más puntos)."""
    pesos = _pesos(_objetivos_zona(n, zona))
    roles = ROLES[zona]
    opciones = []
    for rol in roles:
        lista = list(candidatos[rol.nombre])
        if not rol.obligatorio:
            lista.append(None)
        if not lista:
            return []
        opciones.append(lista)

    validas = []
    for combinacion in itertools.product(*opciones):
        sel = dict(zip((r.nombre for r in roles), combinacion))
        ids = [c.id for c in combinacion if c]
        # Un producto no se repite en dos pasos (tampoco el mismo sérum de mañana y de noche)
        if len(ids) != len(set(ids)):
            continue
        resultado = _evaluar(zona, sel, n, pesos)
        if resultado:
            validas.append(resultado)

    frontera = _frontera(validas)
    if zona == "cara" and candidatos.get("capa_hidratante"):
        frontera = _frontera(frontera + _con_capa(frontera, candidatos["capa_hidratante"], n, pesos))
    return frontera


def _frontera(validas: list[dict]) -> list[dict]:
    validas = sorted(validas, key=lambda r: (r["coste"], -r["puntos"]))
    frontera, mejor = [], float("-inf")
    for r in validas:
        if r["puntos"] > mejor + 1e-9:
            frontera.append(r)
            mejor = r["puntos"]
    return frontera


def _con_capa(frontera: list[dict], capas: list[Candidato], n: Necesidades, pesos: dict) -> list[dict]:
    """Añade un sérum hidratante a cada rutina de la frontera cuando compensa un activo fuerte, cubre
    hidratación/barrera o ya lo tienes. Respeta pasos, presupuesto, irritación y conflictos."""
    fijada = "capa_hidratante" in n.fijar_roles
    piel_que_lo_pide = n.tipo_piel in ("seca", "atopica", "madura") or n.sensible \
        or bool({"hidratacion", "barrera", "calmar"} & set(pesos))
    ids_capa = {c.id for c in capas}
    nuevas = []
    for r in frontera:
        activo = r["sel"].get("activo_pm") or r["sel"].get("activo_am")
        fuerte = bool(activo and (activo.irritacion >= 1 or activo.grupos & {"retinoids", "aha", "bha"}))
        bases = [r["sel"]]
        # Si el "sérum de mañana" ya es un hidratante puro, mejor que pase a ser la capa (mañana y noche)
        # que comprar otro hidratante igual
        am = r["sel"].get("activo_am")
        if am and am.id in ids_capa:
            bases.append({**r["sel"], "activo_am": None})
        mejor = None
        for base, capa in itertools.product(bases, capas):
            usados = {c.id for c in base.values() if c}
            if capa.id in usados or any(c and c.id in ids_capa for k, c in base.items()
                                        if k in ("activo_am", "activo_pm")):
                continue      # dos sérums hidratantes iguales no aportan
            nuevo = _evaluar("cara", {**base, "capa_hidratante": capa}, n, pesos)
            if not nuevo:
                continue
            if fuerte and piel_que_lo_pide:
                extra = 1.0
            elif r["sel"].get("activo_pm") or piel_que_lo_pide:
                extra = 0.6       # compensa el tratamiento de noche, o tu piel pide más agua
            else:
                extra = 0.0
            nuevo["puntos"] += extra
            ganancia = nuevo["puntos"] - r["puntos"]
            if (fijada or ganancia >= (0.5 if capa.propio else 1.0)) and (mejor is None or nuevo["puntos"] > mejor["puntos"]):
                if fuerte or r["sel"].get("activo_pm"):
                    capa.motivos = list(dict.fromkeys(capa.motivos + [
                        "Va encima de tu activo para compensar la sequedad o la irritación"]))
                mejor = nuevo
        if mejor:
            nuevas.append(mejor)
    return nuevas


# ---------------------------------------------------------------------------
# 3. Resultado legible
# ---------------------------------------------------------------------------

def _alternativas(zona: str, r: dict, rol: str, opciones: list[Candidato], n: Necesidades,
                  pesos: dict, coste_total: float) -> list[dict]:
    """Hasta 2 productos que podrían ocupar este paso sin romper la rutina (presupuesto, pasos,
    irritación, conflictos), ordenados de mejor a peor. La persona elige en la web."""
    actual = r["sel"][rol]
    usados = {c.id for c in r["sel"].values() if c}
    # Si el mismo producto ocupa dos pasos (sérum de mañana y de noche), se cambian los dos
    roles = [x for x, c in r["sel"].items() if c and c.id == actual.id]
    validas = []
    for c in opciones:
        if c.id in usados:
            continue
        if any(c.p.get("momento") == ("pm" if x == "activo_am" else "am")
               for x in roles if x in ("activo_am", "activo_pm")):
            continue
        sel = {**r["sel"], **{x: c for x in roles}}
        nuevo = _evaluar(zona, sel, n, pesos)
        if not nuevo:
            continue
        coste = coste_total - r["coste"] + nuevo["coste"]
        if n.presupuesto is not None and coste > n.presupuesto + 1e-9:
            continue
        validas.append((nuevo["puntos"], c))
    validas.sort(key=lambda x: -x[0])
    resultado = []
    for _, c in validas[:2]:
        cubre = [OBJETIVOS_ES.get(o, o) for o in pesos if o in c.objetivos]
        resultado.append({
            "producto": catalogo.resumen(c.p),
            "diferencia_precio": round((c.p["precio"] or 0) - (actual.p["precio"] or 0), 2),
            "roles": roles,
            "motivos": (["Para tus objetivos: " + ", ".join(cubre)] if cubre else []) + c.motivos[:3],
            "ya_lo_tienes": c.propio,
        })
    return resultado


def _frecuencia(c: Candidato, alternas: list) -> str:
    pareja = next((y if x == c.id else x for x, y, _ in alternas if c.id in (x, y)), None)
    if pareja:
        otro = catalogo.producto_por_id(pareja)
        return f"Noches alternas con {otro['nombre'] if otro else 'el otro activo'}"
    if "retinoids" in c.grupos:
        return "2-3 noches por semana al principio; ve subiendo poco a poco"
    if c.grupos & {"aha", "bha"} and c.p["paso"] not in ACLARADO and c.irritacion >= 1:
        return "2-3 veces por semana"
    return "A diario"


def _paso(rol: str, c: Candidato, pesos: dict, alternas: list) -> dict:
    p = c.p
    motivos = []
    cubre = [OBJETIVOS_ES.get(o, o) for o in pesos if o in c.objetivos]
    if cubre:
        motivos.append("Para tus objetivos: " + ", ".join(cubre))
    motivos += c.motivos
    real = catalogo.producto_por_id(p["id"])
    return {
        "rol": rol, "rol_nombre": NOMBRE_ROL[rol],
        "producto": catalogo.resumen(real) if real else {
            "id": p["id"], "marca": p["marca"], "nombre": p["nombre"], "precio": None,
            "activos": [ingredientes.nombre(a) for a in p["activos"]], "enlaces": [], "origen": "",
        },
        "ya_lo_tienes": c.propio, "coste": c.coste,
        "frecuencia": _frecuencia(c, alternas), "motivos": motivos,
    }


def _ids_rutina(rutina: dict | None) -> dict[str, str]:
    if not rutina:
        return {}
    return {paso["producto"]["id"]: f"{paso['producto']['marca']} {paso['producto']['nombre']}".strip()
            for zona in rutina.get("zonas", {}).values()
            for seccion in zona.values() for paso in seccion}


def optimizar(necesidades: Necesidades | dict, contexto: dict | None = None,
              opiniones: dict | None = None) -> dict:
    """Calcula la rutina óptima.

    contexto: lo que devuelve usuarios.contexto() (armario, journey, última rutina).
    opiniones: {producto_id: resumen de reseñas}; si es None se lee de la base de datos.
    """
    n = necesidades if isinstance(necesidades, Necesidades) else Necesidades.desde_dict(necesidades)
    ctx = contexto or {}
    if opiniones is None:              # todas las reseñas en una sola consulta
        from app import resenas
        try:
            opiniones = resenas.resumenes(n.tipo_piel)
        except Exception:
            opiniones = {}
    candidatos, opciones, descartes, avisos = _candidatos(n, ctx, opiniones)

    fronteras = {}
    for zona in n.zonas:
        fronteras[zona] = _optimizar_zona(zona, candidatos[zona], n)
        if not fronteras[zona]:
            avisos.append(f"No he encontrado una combinación válida para {zona}: prueba con más pasos, "
                          "más presupuesto o menos restricciones.")
    zonas_ok = [z for z in n.zonas if fronteras[z]]

    # Combinar zonas respetando el presupuesto total
    mejor, mejor_puntos = None, float("-inf")
    for combinacion in itertools.product(*(fronteras[z] for z in zonas_ok)):
        coste = sum(r["coste"] for r in combinacion)
        if n.presupuesto is not None and coste > n.presupuesto + 1e-9:
            continue
        puntos = sum(r["puntos"] for r in combinacion)
        if puntos > mejor_puntos:
            mejor, mejor_puntos = combinacion, puntos
    presupuesto_insuficiente = False
    if mejor is None and zonas_ok:
        # Ni la opción más barata de cada zona cabe: devolvemos la más barata y avisamos
        mejor = tuple(fronteras[z][0] for z in zonas_ok)
        presupuesto_insuficiente = True
        minimo = sum(r["coste"] for r in mejor)
        avisos.append(f"Con {n.presupuesto:.0f} € no llega para una rutina completa: lo mínimo "
                      f"sensato son {minimo:.2f} €. Te propongo esa opción.")

    zonas, compras, ahorro, usados, alternas_total = {}, {}, 0.0, [], []
    combinaciones = []       # lo que dice la matriz de compatibilidad de esta rutina
    coste_total = sum(r["coste"] for r in (mejor or ()))
    for zona, r in zip(zonas_ok, mejor or ()):
        pesos = _pesos(_objetivos_zona(n, zona))
        alternas_total += r["alternas"]
        cache_alternativas = {}
        def alternativas_de(rol, zona=zona, r=r, pesos=pesos, cache=cache_alternativas):
            if rol not in cache:
                cache[rol] = _alternativas(zona, r, rol, opciones[zona][rol], n, pesos, coste_total)
            return cache[rol]
        zonas[zona] = {
            seccion: [{**_paso(rol, r["sel"][rol], pesos, r["alternas"]), "alternativas": alternativas_de(rol)}
                      for rol in roles]
            for seccion, roles in r["secciones"].items() if roles
        }
        # Por qué estos productos van bien juntos (o por qué se alternan), según la matriz
        nombres_sel = {c.id: f"{c.p['marca']} {c.p['nombre']}".strip() for c in r["sel"].values() if c}
        extra_motivos: dict[str, list[str]] = {}
        for (x, y), regla in r.get("sinergias", {}).items():
            combinaciones.append({"tipo": "sinergia", "productos": [nombres_sel[x], nombres_sel[y]],
                                  "titulo": regla["titulo"], "porque": regla["porque"], "como": regla["como"]})
            extra_motivos.setdefault(x, []).append(f"Se potencia con {nombres_sel[y]}: {regla['porque']}")
            extra_motivos.setdefault(y, []).append(f"Se potencia con {nombres_sel[x]}: {regla['porque']}")
        for x, y, como in r["alternas"]:
            combinaciones.append({"tipo": "separar", "productos": [nombres_sel[x], nombres_sel[y]],
                                  "titulo": "Mejor en noches distintas", "porque": "", "como": como})
        for pasos in zonas[zona].values():
            for paso in pasos:
                paso["motivos"] = list(dict.fromkeys(paso["motivos"] + extra_motivos.get(paso["producto"]["id"], [])[:2]))
        for c in {c.id: c for c in r["sel"].values() if c}.values():
            usados.append((zona, c))
            if c.propio:
                ahorro += c.p.get("precio") or 0
            else:
                compras[c.id] = {**catalogo.resumen(c.p), "zona": zona}

    # Plan de introducción: un producto nuevo por semana, de lo más suave a lo más activo
    nuevos = sorted((c for z, c in usados if not c.propio and z == "cara"),
                    key=lambda c: (c.p["paso"] not in ("limpiador", "hidratante", "spf"), c.irritacion))
    plan = [f"Semana {i}: empieza con {c.p['marca']} {c.p['nombre']}" for i, c in enumerate(nuevos, 1)]
    if any(not c.propio for z, c in usados if z != "cara"):
        plan.append("Cuerpo y pelo: puedes empezar a la vez, desde la primera semana")

    grupos_usados = {g for _, c in usados for g in c.grupos}
    if grupos_usados & {"retinoids", "aha", "bha", "vitamin_c_pure"}:
        avisos.append("Usa protector solar cada mañana: tus activos aumentan la sensibilidad al sol.")
    if n.sensible:
        avisos.append("Haz una prueba de tolerancia de 48 h (detrás de la oreja) con cada producto nuevo.")
    if n.embarazo:
        avisos.append("He dejado fuera retinoides y activos desaconsejados en el embarazo; "
                      "consulta cualquier duda con tu médico o matrona.")
    if n.clima == "frio_seco":
        avisos.append("En el frío: reduce exfoliantes y retinoides a 1-2 noches por semana y sella con la crema.")
    if n.clima in ("calor_humedo", "sol_intenso"):
        avisos.append("Con calor y sol: reaplica el protector cada 2 horas y después de bañarte.")

    # Lo del armario que no ha entrado, y por qué (para que no parezca que lo ignora)
    usados_ids = {c.id for _, c in usados}
    por_paso = {c.p["paso"]: f"{c.p['marca']} {c.p['nombre']}".strip() for _, c in usados}
    armario_sin_usar = []
    for q in _propios(ctx, n):
        if q["id"] in usados_ids or q["zona"] not in n.zonas:
            continue
        nombre_q = f"{q['marca']} {q['nombre']}".strip()
        aviso = next((a for a in avisos if nombre_q in a), None)
        if aviso:
            motivo = aviso.split(": ", 1)[-1].rstrip(".")
        elif q["paso"] in ("contorno", "mascarilla", "puntual", "mascarilla_capilar"):
            motivo = "es un extra: úsalo aparte (contorno a diario, mascarilla 1-2 veces por semana)"
        elif q["paso"] in por_paso:
            motivo = f"en ese paso encaja mejor {por_paso[q['paso']]}; puedes elegirlo en «otras opciones»"
        else:
            motivo = "no cabe en el número de pasos o choca con otro activo de la rutina"
        armario_sin_usar.append({"producto": nombre_q, "id": q["id"], "motivo": motivo})

    anteriores = _ids_rutina(ctx.get("ultima_rutina"))
    actuales = {c.id: f"{c.p['marca']} {c.p['nombre']}".strip() for _, c in usados}
    cambios = {"anade": [v for k, v in actuales.items() if k not in anteriores],
               "quita": [v for k, v in anteriores.items() if k not in actuales]} if anteriores else None

    total = round(sum(c["precio"] or 0 for c in compras.values()), 2)
    return {
        "zonas": zonas,
        "compras": list(compras.values()),
        "total_compras": total,
        "presupuesto": n.presupuesto,
        "presupuesto_insuficiente": presupuesto_insuficiente,
        "ahorro_armario": round(ahorro, 2),
        "pasos_max": n.max_pasos,
        "plan_introduccion": plan,
        "avisos": list(dict.fromkeys(avisos)),
        "descartes": descartes,
        "armario_sin_usar": armario_sin_usar,
        "cambios": cambios,
        "combinaciones": combinaciones,
        "necesidades": asdict(n),
    }


def resumen_texto(rutina: dict) -> str:
    """Resumen compacto de la rutina para el LLM (que la explicará al usuario)."""
    lineas = []
    titulos = {"manana": "MAÑANA", "noche": "NOCHE", "ducha": "CUERPO - en la ducha",
               "despues": "CUERPO - después", "lavado": "PELO - lavado", "acabado": "PELO - acabado"}
    for zona in rutina["zonas"].values():
        for seccion, pasos in zona.items():
            lineas.append(titulos[seccion] + ":")
            for i, paso in enumerate(pasos, 1):
                p = paso["producto"]
                precio = "ya lo tiene" if paso["ya_lo_tienes"] else f"{p.get('precio') or 0:.2f} €"
                lineas.append(f"  {i}. {paso['rol_nombre']}: [ref:{p['id']}] {p['marca']} {p['nombre']} "
                              f"({precio}) · {paso['frecuencia']} · activos: {', '.join(p.get('activos', []))}"
                              f" · {'; '.join(paso['motivos'])}")
    lineas.append(f"Total a comprar: {rutina['total_compras']:.2f} €"
                  + (f" de {rutina['presupuesto']:.0f} € de presupuesto" if rutina["presupuesto"] else "")
                  + (f" · ahorro por usar lo que ya tiene: {rutina['ahorro_armario']:.2f} €"
                     if rutina["ahorro_armario"] else ""))
    if rutina["cambios"]:
        lineas.append(f"Cambios respecto a su rutina anterior: añade {rutina['cambios']['anade']}, "
                      f"quita {rutina['cambios']['quita']}")
    if rutina["descartes"]:
        lineas.append("Descartados: " + "; ".join(f"{d['producto']} ({d['motivo']})" for d in rutina["descartes"]))
    for c in rutina.get("combinaciones", []):
        lineas.append(f"Compatibilidad ({c['titulo']}): {' + '.join(c['productos'])}. {c['porque']} {c['como']}".strip())
    lineas += [f"Aviso: {a}" for a in rutina["avisos"]]
    lineas += rutina["plan_introduccion"]
    return "\n".join(lineas)
