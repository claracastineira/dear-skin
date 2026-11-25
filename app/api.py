"""API web con FastAPI: sirve la página HTML y conecta la web con LangGraph y el optimizador.

Arranque:
    uvicorn app.api:app --reload
y abre http://localhost:8000  (documentación interactiva en /docs)

Todo lo que no necesita conversación (rutina desde formulario, "¿merece la pena?", armario,
skin journey, reseñas) funciona aunque el LLM no esté disponible.
"""

import logging
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import auditoria, catalogo, compatibilidad, hype, resenas, rutina, usuarios
from app.ingredientes import matriz as ingredientes_matriz
from app.config import RAIZ

log = logging.getLogger("dear-skin")
PATRON_REF = re.compile(r"\s*\[ref:([a-z0-9\-]+)\]")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Al arrancar: bases de datos, servidor MCP y grafo. Si falla el LLM, la web sigue funcionando."""
    resenas.inicializar()
    usuarios.conectar().close()
    app.state.grafo = None
    try:
        from app.agentes import herramientas_mcp
        from app.grafo import construir_grafo

        async with herramientas_mcp() as herramientas:
            app.state.grafo = construir_grafo(herramientas)
            yield
    except Exception as error:  # sin clave, sin ingesta...: el chat queda desactivado
        if app.state.grafo is not None:
            raise
        log.warning("Chat desactivado (%s). Revisa .env y ejecuta python -m app.ingesta", error)
        app.state.error_chat = str(error)
        yield


app = FastAPI(title="Dear Skin · personal shopper de skincare coreano", lifespan=ciclo_de_vida)


# ---------- Modelos de entrada ----------

class NuevoUsuario(BaseModel):
    alias: str = Field(min_length=1, max_length=40)
    perfil: dict = Field(default_factory=dict)


class ArticuloArmario(BaseModel):
    momento: str = "ambos"
    producto_id: str | None = None
    nombre: str = ""
    paso: str = ""
    zona: str = "cara"
    activos: list[str] = Field(default_factory=list)
    desde: str | None = None


class EntradaDiario(BaseModel):
    productos: list[str] = Field(default_factory=list)
    tolerancia: int = Field(ge=1, le=5)
    reaccion: bool = False
    sintomas: list[str] = Field(default_factory=list)
    notas: str = Field(default="", max_length=1000)
    compartir_resena: bool = False


class PeticionRutina(BaseModel):
    usuario_id: str | None = None
    necesidades: dict = Field(default_factory=dict)


class EleccionRutina(BaseModel):
    usuario_id: str | None = None
    necesidades: dict = Field(default_factory=dict)   # las de la rutina actual (si no, la guardada)
    producto_id: str
    roles: list[str] = Field(min_length=1)


class PeticionHype(BaseModel):
    producto: str = Field(min_length=2, max_length=200)
    usuario_id: str | None = None


class PeticionCompatibilidad(BaseModel):
    elementos: list[str] = Field(min_length=2, max_length=6)
    usuario_id: str | None = None


class MensajeChat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=2000)
    usuario_id: str | None = None
    sesion_id: str | None = None


class NuevaResena(BaseModel):
    producto_id: str
    alias: str = Field(default="anónimo", max_length=40)
    tipo_piel: str = Field(min_length=1, max_length=30)
    puntuacion: int = Field(ge=1, le=5)
    semanas_uso: int = Field(ge=0, le=520)
    reaccion: bool = False
    texto: str = Field(default="", max_length=1000)


def _usuario(uid: str) -> None:
    if not usuarios.existe(uid):
        raise HTTPException(404, "Usuario no encontrado")


def _tarjeta(p: dict) -> dict:
    stats = resenas.resumen(p["id"])
    return {**catalogo.resumen(p), "resenas": {"total": stats["total"], "media": stats.get("media")}}


# ---------- Usuarios: perfil, armario y skin journey ----------

@app.post("/api/usuarios", status_code=201)
def crear_usuario(datos: NuevoUsuario):
    uid = usuarios.crear_usuario(datos.alias, datos.perfil)
    return {"id": uid, "perfil": usuarios.obtener_perfil(uid)}


@app.get("/api/usuarios/{uid}")
def ver_usuario(uid: str):
    _usuario(uid)
    ctx = usuarios.contexto(uid)
    return {**ctx, "diario": usuarios.diario(uid)[:20]}


@app.put("/api/usuarios/{uid}/perfil")
def actualizar_perfil(uid: str, cambios: dict):
    _usuario(uid)
    return usuarios.guardar_perfil(uid, cambios)


@app.post("/api/usuarios/{uid}/armario", status_code=201)
def anadir_armario(uid: str, item: ArticuloArmario):
    _usuario(uid)
    if item.producto_id:
        p = catalogo.producto_por_id(item.producto_id)
        if not p:
            raise HTTPException(404, "Producto no encontrado")
        nuevo = usuarios.anadir_al_armario(uid, f"{p['marca']} {p['nombre']}", p["paso"], p["zona"],
                                           p["id"], p["activos"], item.desde, item.momento)
    else:
        if not item.nombre or not item.paso:
            raise HTTPException(422, "Indica el nombre y el paso (limpiador, hidratante, spf...)")
        nuevo = usuarios.anadir_al_armario(uid, item.nombre, rutina.normalizar_paso(item.paso), item.zona,
                                           None, item.activos, item.desde, item.momento)
    return {"id": nuevo, "armario": usuarios.armario(uid)}


@app.put("/api/usuarios/{uid}/armario/{item_id}")
def momento_armario(uid: str, item_id: int, datos: dict):
    _usuario(uid)
    usuarios.cambiar_momento(uid, item_id, datos.get("momento", "ambos"))
    return {"armario": usuarios.armario(uid)}


class PeticionRevision(BaseModel):
    usuario_id: str | None = None
    rutina: dict
    perfil: dict = Field(default_factory=dict)   # para quien no tiene perfil guardado


@app.post("/api/revisar")
def revisar_rutina(peticion: PeticionRevision):
    """Revisa la rutina que la persona usa hoy (sin LLM) y la guarda si tiene perfil."""
    ctx = usuarios.contexto(peticion.usuario_id or "")
    if ctx["usuario_id"]:
        usuarios.guardar_rutina_actual(ctx["usuario_id"], peticion.rutina)
    return auditoria.analizar(peticion.rutina, ctx, peticion.perfil or None)


@app.get("/api/usuarios/{uid}/rutina-actual")
def ver_rutina_actual(uid: str):
    _usuario(uid)
    return usuarios.rutina_actual(uid) or {"manana": [], "noche": []}


@app.delete("/api/usuarios/{uid}/armario/{item_id}")
def quitar_armario(uid: str, item_id: int):
    _usuario(uid)
    if not usuarios.quitar_del_armario(uid, item_id):
        raise HTTPException(404, "Ese producto no está en tu armario")
    return {"armario": usuarios.armario(uid)}


@app.post("/api/usuarios/{uid}/diario", status_code=201)
def anotar_diario(uid: str, entrada: EntradaDiario):
    _usuario(uid)
    usuarios.anotar_diario(uid, entrada.productos, entrada.tolerancia, entrada.reaccion,
                           entrada.sintomas, entrada.notas)
    if entrada.compartir_resena:
        # Lo que anotas en tu diario también ayuda a otras personas (como reseña)
        perfil = usuarios.obtener_perfil(uid)
        seguimiento = usuarios.resumen_journey(uid)["seguimiento"]
        for pid in entrada.productos:
            if catalogo.producto_por_id(pid):
                resenas.guardar_resena({
                    "producto_id": pid, "alias": perfil.get("alias", "anónimo"),
                    "tipo_piel": perfil.get("tipo_piel") or "normal", "puntuacion": entrada.tolerancia,
                    "semanas_uso": seguimiento.get(pid, {}).get("semanas", 0),
                    "reaccion": entrada.reaccion, "texto": entrada.notas})
    return {"journey": usuarios.resumen_journey(uid), "diario": usuarios.diario(uid)[:20]}


# ---------- Rutina y "¿merece la pena?" (sin LLM) ----------

@app.post("/api/rutina")
def generar_rutina(peticion: PeticionRutina):
    ctx = usuarios.contexto(peticion.usuario_id or "")
    perfil = ctx["perfil"]
    necesidades = {"tipo_piel": perfil.get("tipo_piel") or "normal", "sensible": perfil.get("sensible"),
                   "tipo_pelo": perfil.get("tipo_pelo"), "embarazo": perfil.get("embarazo"),
                   "evitar_ingredientes": perfil.get("evitar") or [], "objetivos": perfil.get("objetivos") or [],
                   "deseos": perfil.get("deseos") or [], "max_pasos": perfil.get("max_pasos"),
                   "presupuesto": perfil.get("presupuesto"),
                   **{k: v for k, v in peticion.necesidades.items() if v not in (None, "")}}
    resultado = rutina.optimizar(necesidades, ctx)
    if ctx["usuario_id"]:
        usuarios.guardar_rutina(ctx["usuario_id"], resultado)
    return resultado


@app.post("/api/rutina/elegir")
def elegir_opcion(eleccion: EleccionRutina):
    """La persona elige otra de las opciones de un paso: se fija y se recalcula el resto."""
    if not catalogo.producto_por_id(eleccion.producto_id):
        raise HTTPException(404, "Producto no encontrado")
    ctx = usuarios.contexto(eleccion.usuario_id or "")
    base = dict(eleccion.necesidades or (ctx["ultima_rutina"] or {}).get("necesidades") or {})
    base["fijar_roles"] = {**(base.get("fijar_roles") or {}), **{r: eleccion.producto_id for r in eleccion.roles}}
    base["excluir_productos"] = [x for x in base.get("excluir_productos") or [] if x != eleccion.producto_id]
    resultado = rutina.optimizar(base, ctx)
    if ctx["usuario_id"]:
        usuarios.guardar_rutina(ctx["usuario_id"], resultado)
    return resultado


@app.get("/api/usuarios/{uid}/rutina")
def ultima_rutina(uid: str):
    _usuario(uid)
    return usuarios.ultima_rutina(uid)


@app.post("/api/hype")
def merece_la_pena(peticion: PeticionHype):
    return hype.analizar(peticion.producto, usuarios.contexto(peticion.usuario_id or ""))


@app.post("/api/compatibilidad")
def comprobar_compatibilidad(peticion: PeticionCompatibilidad):
    """¿Se pueden juntar? Productos o ingredientes contra la matriz de compatibilidad."""
    perfil = usuarios.contexto(peticion.usuario_id or "")["perfil"]
    return compatibilidad.analizar(peticion.elementos, perfil.get("tipo_piel") or "", bool(perfil.get("sensible")))


@app.get("/api/compatibilidad/matriz")
def matriz_compatibilidad():
    m = ingredientes_matriz()
    return {"tipos": m["tipos"], "familias": {k: {c: v for c, v in f.items() if c != "ids"} for k, f in m["familias"].items()},
            "relaciones": m["relaciones"], "fuentes": m["fuentes"], "aviso": m["aviso"]}


# ---------- Chat (LangGraph) ----------

def _resumen_paso(nodo: str, cambios: dict) -> str | None:
    if nodo == "supervisor":
        destino = cambios.get("siguiente")
        return None if destino == "FIN" else f"Supervisor → {destino}"
    if nodo in ("responder", "cargar_usuario"):
        return None
    return f"{nodo} ha terminado"


@app.post("/api/chat")
async def chat(entrada: MensajeChat):
    if app.state.grafo is None:
        raise HTTPException(503, "El chat no está disponible: revisa la clave del LLM en .env y que "
                            "hayas ejecutado python -m app.ingesta. Mientras, puedes usar el formulario "
                            "de rutina y «¿Merece la pena?».")
    from app.grafo import entrada_turno

    uid = entrada.usuario_id if entrada.usuario_id and usuarios.existe(entrada.usuario_id) else ""
    sesion = entrada.sesion_id or uid or str(uuid.uuid4())
    config = {"configurable": {"thread_id": sesion}}
    pasos, respuesta, rutina_nueva, analisis, revision = [], "", None, None, None
    try:
        async for paso in app.state.grafo.astream(entrada_turno(entrada.mensaje, uid), config,
                                                  stream_mode="updates"):
            for nodo, cambios in paso.items():
                cambios = cambios or {}
                if resumen := _resumen_paso(nodo, cambios):
                    pasos.append(resumen)
                if nodo == "personal_shopper":
                    rutina_nueva = cambios.get("rutina")
                if nodo == "detector_hype":
                    analisis = cambios.get("hype")
                if nodo == "revisor_rutina":
                    revision = cambios.get("revision")
                if nodo == "responder":
                    respuesta = cambios["messages"][-1].text
    except Exception as error:  # p. ej. error 429 del plan gratuito de Groq
        raise HTTPException(502, f"El modelo no ha podido responder: {error}") from error

    ids = list(dict.fromkeys(PATRON_REF.findall(respuesta)))
    productos = [_tarjeta(p) for i in ids if (p := catalogo.producto_por_id(i))]
    return {"sesion_id": sesion, "respuesta": PATRON_REF.sub("", respuesta).strip(),
            "productos": productos, "rutina": rutina_nueva, "hype": analisis, "revision": revision, "pasos": pasos}


# ---------- Catálogo y reseñas ----------

@app.get("/api/productos")
def listar_productos(q: str = "", zona: str = "", paso: str = "", limite: int = 30):
    if q:
        return [_tarjeta(p) for _, p in catalogo.buscar_texto(q, limite, zona, paso)]
    lista = [p for p in catalogo.cargar_productos()
             if (not zona or p["zona"] == zona) and (not paso or p["paso"] == paso)]
    return [_tarjeta(p) for p in lista[:max(1, min(limite, 500))]]


@app.get("/api/productos/{producto_id}")
def ver_producto(producto_id: str):
    p = catalogo.producto_por_id(producto_id)
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    return _tarjeta(p)


@app.get("/api/productos/{producto_id}/resenas")
def resenas_producto(producto_id: str, tipo_piel: str = ""):
    if not catalogo.producto_por_id(producto_id):
        raise HTTPException(404, "Producto no encontrado")
    return {"resumen": resenas.resumen(producto_id, tipo_piel),
            "resenas": resenas.listar_resenas(producto_id)}


@app.post("/api/resenas", status_code=201)
def crear_resena(resena: NuevaResena):
    if not catalogo.producto_por_id(resena.producto_id):
        raise HTTPException(404, "Producto no encontrado")
    return {"id": resenas.guardar_resena(resena.model_dump())}


# La web estática (index.html, estilos y JS). Va al final para no tapar /api.
app.mount("/", StaticFiles(directory=RAIZ / "frontend", html=True), name="web")
