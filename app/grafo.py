"""Orquestación con LangGraph.

    INICIO -> cargar_usuario -> supervisor -> especialista -> supervisor -> ... -> responder -> FIN

Especialistas:
  - personal_shopper      LLM (salida estructurada) extrae tus Necesidades -> el OPTIMIZADOR
                          (app/rutina.py, determinista) calcula la rutina -> se guarda en la BD
  - detector_hype         análisis determinista de "¿merece la pena?" (app/hype.py)
  - asesor_productos      agente LangChain con la herramienta MCP buscar_productos (RAG)
  - experto_ingredientes  agente LangChain con la herramienta MCP explicar_ingrediente (RAG)
  - analista_resenas      agente LangChain con la herramienta MCP ver_resenas

Memoria:
  - corto plazo: el checkpointer de LangGraph guarda la conversación (thread_id)
  - largo plazo: cargar_usuario lee de SQLite tu perfil, armario, skin journey y última rutina
"""

import json
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field

from app import auditoria, catalogo, hype, rutina, usuarios
from app.agentes import crear_especialistas
from app.config import crear_modelo

MAX_PASOS = 4          # especialistas por pregunta (límite de seguridad y de llamadas al LLM)
HISTORIAL = 12         # últimos mensajes de la conversación que ven los nodos
REINICIAR = "__reiniciar__"


def acumular(actual: list[str] | None, nuevo: list[str]) -> list[str]:
    """Reductor de 'hallazgos': añade, salvo que llegue la marca de reinicio (nueva pregunta)."""
    if nuevo and nuevo[0] == REINICIAR:
        return list(nuevo[1:])
    return (actual or []) + nuevo


class Estado(MessagesState):
    usuario_id: str
    contexto: dict                                  # perfil, armario, journey, última rutina
    siguiente: str
    tarea: str
    hallazgos: Annotated[list[str], acumular]
    rutina: dict | None                             # rutina generada en esta pregunta
    hype: dict | None                               # análisis "¿merece la pena?" de esta pregunta
    revision: dict | None                           # revisión de su rutina actual


ESPECIALISTAS = ("personal_shopper", "revisor_rutina", "detector_hype", "asesor_productos", "experto_ingredientes",
                 "analista_resenas", "FIN")
OBJETIVOS = ("acne", "poros", "grasa", "luminosidad", "manchas", "hidratacion", "calmar", "rojeces",
             "barrera", "antiedad", "textura", "ojeras", "piel_aspera", "granitos_cuerpo", "brillo",
             "reparar", "encrespamiento", "caspa", "cuero_graso", "caida", "volumen", "hidratacion_pelo")

# Los esquemas usan texto libre (no enumerados cerrados): si el LLM se inventa un valor
# ("bolsas_ojeras"), Groq rechazaría la respuesta entera. Lo limpiamos después en Python.


class Decision(BaseModel):
    """Respuesta estructurada del supervisor."""

    siguiente: str = Field(description="Quién actúa ahora: " + ", ".join(ESPECIALISTAS) + ".")
    tarea: str = Field(default="", description="Encargo autocontenido para el especialista (con tipo de piel, "
                       "objetivos, presupuesto, ids [ref:...]). Para detector_hype: SOLO el nombre del "
                       "producto. Vacío si FIN.")


class NecesidadesLLM(BaseModel):
    """Lo que el personal shopper entiende de la conversación."""

    zonas: list[str] = Field(default_factory=list, description="De entre: cara, cuerpo, pelo.")
    tipo_piel: str = Field("", description="grasa, seca, mixta, normal, acneica, madura o atopica.")
    sensible: bool | None = None
    tipo_pelo: str = Field("", description="graso, seco, dañado, teñido, rizado, fino, caspa o normal.")
    objetivos: list[str] = Field(default_factory=list,
                                 description="Por orden de prioridad, SOLO de entre: " + ", ".join(OBJETIVOS))
    presupuesto: float | None = Field(None, description="Euros para comprar lo que falta.")
    max_pasos: int | None = Field(None, description="Pasos máximos por rutina. 'Sin diez pasos' -> 4.")
    evitar_ingredientes: list[str] = Field(default_factory=list)
    embarazo: bool | None = None
    clima: str = Field("", description="Vacío, frio_seco, calor_humedo o sol_intenso (viajes).")
    ya_tengo: list[str] = Field(default_factory=list,
                                description="Pasos que ya tiene sin dar marca: 'hidratante', 'spf'...")
    excluir_productos: list[str] = Field(default_factory=list,
                                         description="ids [ref:...] que no quiere NI QUIERE nada parecido.")
    cambiar_por_similar: list[str] = Field(default_factory=list, description=(
        "ids o nombres de productos que no le gustan (textura, precio, marca) pero cuya FUNCIÓN sí quiere: "
        "'no me gusta este retinol porque es aceitoso' -> el retinol va aquí."))
    evitar_texturas: list[str] = Field(default_factory=list, description=(
        "texturas que no le gustan: textura_oleosa (aceitoso, graso), textura_rica (pesado, pegajoso)."))
    fijar_productos: list[str] = Field(default_factory=list,
                                       description="ids [ref:...] que quiere mantener sí o sí.")
    precio_max_producto: float | None = None


def _objetivos_validos(valores: list[str]) -> list[str]:
    """Traduce lo que dé el LLM (o el usuario) a objetivos del catálogo, tolerando erratas."""
    return list(dict.fromkeys(o for v in valores for o in catalogo.interpretar(v, OBJETIVOS)))


PROMPT_SUPERVISOR = """Eres el supervisor de Dear Skin, un personal shopper de skincare coreano con IA
(cara, cuerpo y pelo). No respondes al usuario: decides qué especialista actúa.

- personal_shopper: crea o MODIFICA la rutina completa personalizada (mañana/noche, cuerpo, pelo).
  También si solo dice "hazme una rutina" o "con lo que tengo": usa su perfil y su armario guardados.
  Úsalo si pide una rutina, describe su piel + objetivos + presupuesto, quiere cambiar un producto
  de su rutina ("es muy caro", "no me gusta"), o se va de viaje / cambia el clima.
- revisor_rutina: REVISA la rutina que la persona usa hoy (la apunta en «Revisar mi rutina»): qué está
  bien, qué no juntar, qué sobra, si satura la piel y una semana propuesta. Úsalo si pide opinión sobre
  SU rutina actual ("¿está bien mi rutina?", "¿qué me sobra?", "¿puedo juntar X e Y?").
- detector_hype: "¿merece la pena X?", productos virales de TikTok. Tarea = solo el nombre.
- asesor_productos: recomienda productos sueltos de un tipo concreto (no una rutina entera).
- experto_ingredientes: explica qué es un ingrediente, si se pueden JUNTAR productos o activos
  ("¿puedo usar retinol y ácidos?", "¿qué pongo después del retinol?"), clima, cómo introducir activos.
  En la tarea pon los nombres exactos de los productos o ingredientes.
- analista_resenas: reseñas de productos concretos (necesita ids [ref:...]).

Flujos habituales:
- Rutina: personal_shopper -> experto_ingredientes (explica los 2-3 activos clave elegidos) -> FIN.
- Revisar su rutina: revisor_rutina -> FIN.
- Hype: detector_hype -> FIN (o experto_ingredientes si no está en el catálogo).
- Producto suelto: asesor_productos -> FIN.
Preguntas sobre su skin journey, su armario o su perfil: FIN (el redactor tiene esos datos).

Lo que sabemos del usuario:
{contexto}

Información recogida en esta pregunta:
{hallazgos}

Responde FIN cuando haya información suficiente o si solo saluda.
Nunca escribas la respuesta para el usuario: rellena SIEMPRE el esquema (siguiente y tarea)."""

PROMPT_NECESIDADES_EXTRA = """
Si dice que un producto no le gusta por su textura, precio o marca pero quiere algo que haga lo mismo,
ponlo en cambiar_por_similar (y la textura en evitar_texturas). Usa excluir_productos solo si no quiere
nada de ese tipo. Los productos de su armario son lo primero: no los quites si no lo pide."""

PROMPT_NECESIDADES = """Extrae las necesidades para construir la rutina de skincare a partir de la
conversación. Si el usuario no dice algo, déjalo vacío: se completará con su perfil guardado.
El usuario puede escribir con erratas o juntar cosas ("bolsas-ojeras", "granitoss y manchas"):
interpreta lo que quiso decir y sepáralo en varios objetivos si hace falta.
Si el usuario CORRIGE lo que entendiste antes ("no, me refería a..."), haz caso a su corrección y
devuelve la lista de objetivos completa ya corregida.""" + PROMPT_NECESIDADES_EXTRA + """
Si quiere MODIFICAR la rutina anterior, devuelve solo lo que cambia (p. ej. excluir_productos con el
id del producto que le parece caro, o un clima si se va de viaje).

Perfil guardado: {perfil}
Rutina anterior (ids y necesidades): {anterior}"""

PROMPT_RESPUESTA = """Eres Dear Skin, un personal shopper de skincare coreano con IA. Responde en español,
cercano y claro, usando SOLO esta información:

{hallazgos}

Lo que sabes del usuario (perfil, armario, skin journey):
{contexto}

Reglas:
- PROHIBIDO escribir tablas, HTML o listas de productos que no aparezcan arriba. NUNCA inventes productos,
  opciones ni datos: si no está en la información recogida, no existe. Usa frases y listas cortas.
- Si hay una REVISIÓN de su rutina, la web la muestra completa (nota, problemas, semana propuesta):
  resume en 4-6 frases lo más importante (primero lo grave), explica el porqué en lenguaje sencillo y
  anímale a mirar la semana propuesta.
- Si hay una RUTINA nueva, empieza con UNA línea que diga lo que has entendido (tipo de piel,
  objetivos, presupuesto, pasos, clima) para que la persona pueda corregirte, por ejemplo:
  "He entendido: piel seca y sensible · ojeras y manchas · 100 € · máximo 5 pasos. Si no es así, dímelo."
- Si hay una RUTINA nueva, la web la muestra en una tarjeta con foto, explicación de cada producto,
  precios, enlaces de compra y OTRAS OPCIONES en cada paso para que la persona elija: NO copies la
  lista entera; recuérdale que puede elegir otra opción en cada paso o pedirte cambios. Explica en pocas frases la lógica (por qué estos productos para
  su piel y objetivos, qué aprovecha de lo que ya tiene, cuánto gasta), explica en lenguaje sencillo
  los 2-3 ingredientes clave ("el retinol es un derivado de la vitamina A que...") y cómo
  introducirlos. Si hay cambios respecto a la rutina anterior, dilos. Termina ofreciendo ajustar
  algo ("si algún producto no te convence o te parece caro, dímelo").
- Si recomiendas productos sueltos, da 2-3 OPCIONES para que la persona elija. Para cada una:
  **Marca · Nombre** [ref:id] — precio aproximado, y 3-4 frases: qué es y cómo es su textura, por qué
  encaja con SU piel y lo que pide, qué hacen sus ingredientes clave en lenguaje sencillo y cómo
  usarlo. Termina con una frase que ayude a decidir ("si priorizas precio, la 2; si tu piel es muy
  sensible, la 1"). La web muestra cada opción en una tarjeta con foto, botón de compra y botón
  "Elegir esta".
- Si es un análisis de "¿merece la pena?", da el veredicto claro y el porqué (equivalentes que ya
  tiene, qué aporta, evidencia, alternativas más baratas).
- Si en su skin journey algo le sentó mal, tenlo en cuenta y dilo con tacto.
- Nunca diagnostiques enfermedades. Si describe algo serio (acné severo, reacción fuerte, lesiones
  que cambian), recomienda ir al dermatólogo. Los precios son orientativos.
Si falta un dato imprescindible (tipo de piel), pregúntalo en una frase.
- Muchas personas no saben de skincare y no saben qué pedir. Si dice que no sabe o no hay perfil, hazle
  como mucho 3 preguntas sencillas, sin jerga y con ejemplos: "¿a mediodía te brilla la frente o la nariz?",
  "¿después de lavarte la cara la notas tirante?", "¿te salen granitos, manchas o rojeces?", "¿cuánto
  quieres gastar?". Con sus respuestas ya puedes montar la rutina.
- Usa SIEMPRE lo que tiene en su armario aunque no lo mencione: es lo primero. Si un producto suyo no
  entra, di por qué en una frase.
- Si la información recogida trae líneas de "Compatibilidad", explica en lenguaje sencillo qué productos
  se potencian y cuáles van en noches distintas, y por qué."""


def _contexto_texto(ctx: dict) -> str:
    if not ctx:
        return "Usuario anónimo: no hay perfil guardado."
    perfil = {k: v for k, v in (ctx.get("perfil") or {}).items() if v not in ("", None, [], False)}
    armario = [f"{a['nombre']} ({a['paso']})" for a in ctx.get("armario", [])]
    journey = ctx.get("journey") or {}
    anterior = ctx.get("ultima_rutina")
    partes = [f"Perfil: {json.dumps(perfil, ensure_ascii=False)}",
              f"Armario: {', '.join(armario) or 'vacío'}"]
    if journey.get("registros"):
        partes.append(f"Skin journey: {journey['registros']} registros; le sentaron mal: "
                      f"{journey['reaccionados'] or 'nada'}; tolera bien: {journey['bien_tolerados'] or '-'}; "
                      f"síntomas frecuentes: {journey['sintomas_frecuentes'] or '-'}; "
                      f"notas: {journey['ultimas_notas'] or '-'}")
    if anterior:
        ids = [p["producto"]["id"] for z in anterior["zonas"].values() for s in z.values() for p in s]
        partes.append(f"Tiene una rutina guardada con: {sorted(set(ids))}")
    return "\n".join(partes)


def _necesidades(llm: NecesidadesLLM, ctx: dict) -> dict:
    """Combina: necesidades de la rutina anterior <- perfil guardado <- lo que dice ahora."""
    perfil = ctx.get("perfil") or {}
    anterior = (ctx.get("ultima_rutina") or {}).get("necesidades", {})
    base = {**anterior}
    for clave in ("tipo_piel", "sensible", "tipo_pelo", "embarazo", "presupuesto", "max_pasos",
                  "preferencia_origen", "deseos"):
        if perfil.get(clave) not in ("", None):
            base[clave] = perfil[clave]
    base.setdefault("objetivos", perfil.get("objetivos") or [])
    base["evitar_ingredientes"] = list(dict.fromkeys(
        (anterior.get("evitar_ingredientes") or []) + (perfil.get("evitar") or [])))
    datos = llm.model_dump()
    datos["objetivos"] = _objetivos_validos(datos["objetivos"])
    datos["zonas"] = list(dict.fromkeys(z for v in datos["zonas"] for z in catalogo.interpretar(v, ("cara", "cuerpo", "pelo"))))
    for campo, validos in (("tipo_piel", ("grasa", "seca", "mixta", "normal", "acneica", "madura", "atopica")),
                           ("tipo_pelo", ("graso", "seco", "dañado", "teñido", "rizado", "fino", "caspa", "normal"))):
        encontrados = catalogo.interpretar(datos[campo], validos) if datos[campo] else []
        datos[campo] = encontrados[0] if encontrados else ""
    if datos["clima"] not in ("frio_seco", "calor_humedo", "sol_intenso"):
        datos["clima"] = ""
    for clave, valor in datos.items():
        if valor in (None, "", []):
            continue
        if clave in ("excluir_productos", "evitar_ingredientes", "ya_tengo", "cambiar_por_similar", "evitar_texturas"):
            base[clave] = list(dict.fromkeys((base.get(clave) or []) + valor))
        else:
            base[clave] = valor
    if not base.get("zonas"):
        base["zonas"] = ["cara"]
    # El LLM a veces da nombres en vez de ids: los buscamos en el catálogo
    for clave in ("excluir_productos", "fijar_productos", "cambiar_por_similar"):
        ids = []
        for valor in base.get(clave) or []:
            if catalogo.producto_por_id(valor):
                ids.append(valor)
            elif (encontrados := catalogo.buscar_texto(valor, limite=1)) and encontrados[0][0] >= 0.5:
                ids.append(encontrados[0][1]["id"])
        base[clave] = ids
    return base


async def _estructurado(llm, mensajes: list, intentos: int = 2):
    """Pide una respuesta estructurada. A veces el modelo contesta en texto en vez de rellenar el
    esquema y Groq devuelve 400 'tool_use_failed': reintentamos y, si vuelve a fallar, devolvemos
    None para que el nodo use un plan B en lugar de romper la conversación."""
    for intento in range(intentos):
        try:
            return await llm.ainvoke(mensajes if intento == 0 else [
                *mensajes, HumanMessage("Responde SOLO rellenando el esquema (llamada a la herramienta), "
                                        "sin escribir texto para el usuario.")])
        except Exception as error:  # noqa: BLE001 - errores 400 del proveedor
            if "tool_use_failed" not in str(error) and "validation" not in str(error).lower():
                raise
    return None


def construir_grafo(herramientas: list, modelo=None, checkpointer=None):
    """Compila el grafo. 'herramientas' son las del servidor MCP (ver agentes.herramientas_mcp)."""
    modelo = modelo or crear_modelo()
    especialistas = crear_especialistas(modelo, herramientas)
    decisor = modelo.with_structured_output(Decision)
    extractor = modelo.with_structured_output(NecesidadesLLM)

    def cargar_usuario(estado: Estado) -> dict:
        return {"contexto": usuarios.contexto(estado.get("usuario_id") or "")}

    async def supervisor(estado: Estado) -> dict:
        if len(estado.get("hallazgos") or []) >= MAX_PASOS:
            return {"siguiente": "FIN", "tarea": ""}
        prompt = PROMPT_SUPERVISOR.format(contexto=_contexto_texto(estado["contexto"]),
                                          hallazgos="\n\n".join(estado.get("hallazgos") or []) or "Nada.")
        decision = await _estructurado(decisor, [SystemMessage(prompt), *estado["messages"][-HISTORIAL:]])
        if decision is None:
            # Plan B: si aún no hay información, que el experto conteste con fuentes; si ya hay, a responder
            if estado.get("hallazgos"):
                return {"siguiente": "FIN", "tarea": ""}
            return {"siguiente": "experto_ingredientes", "tarea": estado["messages"][-1].text}
        siguiente = decision.siguiente.strip()
        if siguiente not in ESPECIALISTAS:
            siguiente = "FIN"
        return {"siguiente": siguiente, "tarea": decision.tarea}

    async def personal_shopper(estado: Estado) -> dict:
        ctx = estado["contexto"]
        anterior = ctx.get("ultima_rutina") or {}
        prompt = PROMPT_NECESIDADES.format(
            perfil=json.dumps(ctx.get("perfil") or {}, ensure_ascii=False),
            anterior=json.dumps({"necesidades": anterior.get("necesidades"),
                                 "productos": [c["id"] for c in anterior.get("compras", [])]},
                                ensure_ascii=False) if anterior else "ninguna")
        llm = await _estructurado(extractor, [SystemMessage(prompt), *estado["messages"][-HISTORIAL:]])
        llm = llm or NecesidadesLLM()     # plan B: perfil guardado + rutina anterior
        resultado = rutina.optimizar(_necesidades(llm, ctx), ctx)     # <- el algoritmo
        if ctx.get("usuario_id"):
            usuarios.guardar_rutina(ctx["usuario_id"], resultado)
        return {"rutina": resultado,
                "hallazgos": [f"[personal_shopper] RUTINA NUEVA:\n{rutina.resumen_texto(resultado)}"]}

    def revisor_rutina(estado: Estado) -> dict:
        ctx = estado["contexto"]
        actual = ctx.get("rutina_actual")
        if not actual or not (actual.get("manana") or actual.get("noche")):
            return {"hallazgos": ["[revisor_rutina] No ha apuntado su rutina actual. Dile que la apunte en la "
                                  "pestaña «Revisar mi rutina» (mañana y noche, y qué días usa cada cosa)."]}
        informe = auditoria.analizar(actual, ctx)
        texto = (f"Nota {informe['nota']}/100. Bien: {informe['bien']}. Problemas: "
                 + "; ".join(f"[{p['gravedad']}] {p['titulo']} ({p['cuando']}): {p['detalle']}" for p in informe["problemas"])
                 + f". Sobran/aportan poco: {[(x['producto'], x['motivo']) for x in informe['sobran']]}. "
                 f"Objetivos sin cubrir: {informe['objetivos_sin_cubrir']}. "
                 f"Semana propuesta: {informe['semana_propuesta']['explicacion']}")
        return {"revision": informe, "hallazgos": [f"[revisor_rutina] REVISIÓN DE SU RUTINA: {texto}"]}

    def detector_hype(estado: Estado) -> dict:
        analisis = hype.analizar(estado["tarea"], estado["contexto"])
        return {"hype": analisis,
                "hallazgos": [f"[detector_hype] {json.dumps(analisis, ensure_ascii=False)[:3000]}"]}

    def crear_nodo(nombre: str):
        async def nodo(estado: Estado) -> dict:
            # El especialista solo recibe su encargo, no toda la conversación
            resultado = await especialistas[nombre].ainvoke({"messages": [HumanMessage(estado["tarea"])]})
            return {"hallazgos": [f"[{nombre}] {resultado['messages'][-1].text}"]}
        return nodo

    async def responder(estado: Estado) -> dict:
        prompt = PROMPT_RESPUESTA.format(hallazgos="\n\n".join(estado.get("hallazgos") or []) or "Nada.",
                                         contexto=_contexto_texto(estado["contexto"]))
        respuesta = await modelo.ainvoke([SystemMessage(prompt), *estado["messages"][-HISTORIAL:]])
        return {"messages": [respuesta]}

    grafo = StateGraph(Estado)
    grafo.add_node("cargar_usuario", cargar_usuario)
    grafo.add_node("supervisor", supervisor)
    grafo.add_node("personal_shopper", personal_shopper)
    grafo.add_node("detector_hype", detector_hype)
    grafo.add_node("revisor_rutina", revisor_rutina)
    grafo.add_node("responder", responder)
    for nombre in especialistas:
        grafo.add_node(nombre, crear_nodo(nombre))
    for nombre in [*especialistas, "personal_shopper", "detector_hype", "revisor_rutina"]:
        grafo.add_edge(nombre, "supervisor")      # todos vuelven al supervisor

    grafo.add_edge(START, "cargar_usuario")
    grafo.add_edge("cargar_usuario", "supervisor")
    rutas = {n: n for n in [*especialistas, "personal_shopper", "detector_hype", "revisor_rutina"]} | {"FIN": "responder"}
    grafo.add_conditional_edges("supervisor", lambda estado: estado["siguiente"], rutas)
    grafo.add_edge("responder", END)
    return grafo.compile(checkpointer=checkpointer or InMemorySaver())


def entrada_turno(texto: str, usuario_id: str = "") -> dict:
    """Entrada de una pregunta nueva: mensaje, usuario y reinicio de lo de la pregunta anterior."""
    return {"messages": [HumanMessage(texto)], "usuario_id": usuario_id or "",
            "hallazgos": [REINICIAR], "rutina": None, "hype": None, "revision": None}
