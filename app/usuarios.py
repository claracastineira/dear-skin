"""Usuarios en SQLite: perfil, armario (skincare wardrobe), skin journey y rutinas.

Es la memoria a largo plazo de Dear Skin. El grafo de LangGraph la carga al empezar cada
pregunta (nodo cargar_usuario) y el optimizador de rutinas la usa para:
  - construir la rutina con lo que ya tienes en casa,
  - evitar productos que te sentaron mal y premiar los que toleras bien.

Nota: no hay contraseñas (proyecto educativo). Para producción, añade autenticación.
"""

import json
import secrets
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from app.config import BASE_DATOS

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id      TEXT PRIMARY KEY,
    alias   TEXT NOT NULL,
    perfil  TEXT NOT NULL DEFAULT '{}',
    creado  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS armario (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  TEXT NOT NULL REFERENCES usuarios(id),
    producto_id TEXT,                 -- producto del catálogo, o NULL si es uno propio
    nombre      TEXT NOT NULL,        -- nombre visible (del catálogo o escrito por el usuario)
    zona        TEXT NOT NULL DEFAULT 'cara',
    paso        TEXT NOT NULL,        -- limpiador, hidratante, spf, champu...
    activos     TEXT NOT NULL DEFAULT '[]',
    desde       TEXT NOT NULL         -- fecha en que lo empezó a usar
);
CREATE TABLE IF NOT EXISTS diario (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  TEXT NOT NULL REFERENCES usuarios(id),
    fecha       TEXT NOT NULL,
    productos   TEXT NOT NULL DEFAULT '[]',   -- ids del catálogo o del armario ("armario-3")
    tolerancia  INTEGER NOT NULL CHECK (tolerancia BETWEEN 1 AND 5),
    reaccion    INTEGER NOT NULL DEFAULT 0,
    sintomas    TEXT NOT NULL DEFAULT '[]',   -- rojez, picor, granitos, sequedad, tirantez
    notas       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rutina_actual (
    usuario_id  TEXT PRIMARY KEY REFERENCES usuarios(id),
    datos       TEXT NOT NULL,          -- la rutina que la persona usa hoy, apuntada a mano
    fecha       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rutinas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  TEXT NOT NULL REFERENCES usuarios(id),
    fecha       TEXT NOT NULL,
    rutina      TEXT NOT NULL
);
"""

PERFIL_VACIO = {
    "tipo_piel": "", "sensible": False, "tipo_pelo": "", "evitar": [], "embarazo": False,
    "objetivos": [], "deseos": [], "presupuesto": None, "max_pasos": None, "preferencia_origen": "kbeauty",
}


def conectar(ruta: Path = BASE_DATOS) -> sqlite3.Connection:
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    conexion.executescript(ESQUEMA)
    columnas = {c["name"] for c in conexion.execute("PRAGMA table_info(armario)")}
    if "momento" not in columnas:   # bases creadas con versiones anteriores
        conexion.execute("ALTER TABLE armario ADD COLUMN momento TEXT NOT NULL DEFAULT 'ambos'")
    return conexion


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Usuario y perfil ----------

def crear_usuario(alias: str, perfil: dict | None = None, ruta: Path = BASE_DATOS) -> str:
    usuario_id = "u-" + secrets.token_hex(4)
    with closing(conectar(ruta)) as c:
        c.execute("INSERT INTO usuarios (id, alias, perfil, creado) VALUES (?, ?, ?, ?)",
                  (usuario_id, alias.strip()[:40] or "anónimo",
                   json.dumps({**PERFIL_VACIO, **(perfil or {})}), _ahora()))
        c.commit()
    return usuario_id


def existe(usuario_id: str, ruta: Path = BASE_DATOS) -> bool:
    with closing(conectar(ruta)) as c:
        return c.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone() is not None


def obtener_perfil(usuario_id: str, ruta: Path = BASE_DATOS) -> dict | None:
    with closing(conectar(ruta)) as c:
        fila = c.execute("SELECT alias, perfil FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not fila:
        return None
    return {**PERFIL_VACIO, **json.loads(fila["perfil"]), "alias": fila["alias"]}


def guardar_perfil(usuario_id: str, cambios: dict, ruta: Path = BASE_DATOS) -> dict:
    actual = obtener_perfil(usuario_id, ruta) or dict(PERFIL_VACIO)
    nuevo = {k: v for k, v in {**actual, **cambios}.items() if k in PERFIL_VACIO}
    with closing(conectar(ruta)) as c:
        c.execute("UPDATE usuarios SET perfil = ? WHERE id = ?", (json.dumps(nuevo), usuario_id))
        if cambios.get("alias"):
            c.execute("UPDATE usuarios SET alias = ? WHERE id = ?", (cambios["alias"][:40], usuario_id))
        c.commit()
    return obtener_perfil(usuario_id, ruta)


# ---------- Armario ----------

def anadir_al_armario(usuario_id: str, nombre: str, paso: str, zona: str = "cara",
                      producto_id: str | None = None, activos: list[str] | None = None,
                      desde: str | None = None, momento: str = "ambos", ruta: Path = BASE_DATOS) -> int:
    with closing(conectar(ruta)) as c:
        if producto_id:   # no duplicar el mismo producto
            fila = c.execute("SELECT id FROM armario WHERE usuario_id = ? AND producto_id = ?",
                             (usuario_id, producto_id)).fetchone()
            if fila:
                return fila["id"]
        cursor = c.execute(
            "INSERT INTO armario (usuario_id, producto_id, nombre, zona, paso, activos, desde, momento)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, producto_id, nombre[:120], zona, paso, json.dumps(activos or []),
             desde or date.today().isoformat(), momento if momento in ("manana", "noche") else "ambos"))
        c.commit()
        return cursor.lastrowid


def cambiar_momento(usuario_id: str, item_id: int, momento: str, ruta: Path = BASE_DATOS) -> bool:
    """Cuándo lo usa la persona: 'manana', 'noche' o 'ambos'. El optimizador lo respeta."""
    with closing(conectar(ruta)) as c:
        n = c.execute("UPDATE armario SET momento = ? WHERE id = ? AND usuario_id = ?",
                      (momento if momento in ("manana", "noche") else "ambos", item_id, usuario_id)).rowcount
        c.commit()
    return n > 0


def guardar_rutina_actual(usuario_id: str, datos: dict, ruta: Path = BASE_DATOS) -> None:
    with closing(conectar(ruta)) as c:
        c.execute("INSERT INTO rutina_actual (usuario_id, datos, fecha) VALUES (?, ?, ?) "
                  "ON CONFLICT(usuario_id) DO UPDATE SET datos = excluded.datos, fecha = excluded.fecha",
                  (usuario_id, json.dumps(datos, ensure_ascii=False), _ahora()))
        c.commit()


def rutina_actual(usuario_id: str, ruta: Path = BASE_DATOS) -> dict | None:
    with closing(conectar(ruta)) as c:
        fila = c.execute("SELECT datos FROM rutina_actual WHERE usuario_id = ?", (usuario_id,)).fetchone()
    return json.loads(fila["datos"]) if fila else None


def quitar_del_armario(usuario_id: str, item_id: int, ruta: Path = BASE_DATOS) -> bool:
    with closing(conectar(ruta)) as c:
        n = c.execute("DELETE FROM armario WHERE id = ? AND usuario_id = ?", (item_id, usuario_id)).rowcount
        c.commit()
    return n > 0


def armario(usuario_id: str, ruta: Path = BASE_DATOS) -> list[dict]:
    with closing(conectar(ruta)) as c:
        filas = c.execute("SELECT * FROM armario WHERE usuario_id = ? ORDER BY zona, paso",
                          (usuario_id,)).fetchall()
    from app import catalogo
    lista = []
    for f in filas:
        item = {**dict(f), "activos": json.loads(f["activos"])}
        # 'serum_hidratante' -> paso 'serum' + objetivos del subtipo (para los productos apuntados a mano)
        item["subtipo"] = item["paso"] if item["paso"] in catalogo.SUBTIPOS else ""
        item["paso"], item["objetivos"] = catalogo.paso_y_objetivos(item["paso"])
        lista.append(item)
    return lista


# ---------- Skin journey ----------

def anotar_diario(usuario_id: str, productos: list[str], tolerancia: int, reaccion: bool = False,
                  sintomas: list[str] | None = None, notas: str = "", fecha: str | None = None,
                  ruta: Path = BASE_DATOS) -> int:
    with closing(conectar(ruta)) as c:
        cursor = c.execute(
            "INSERT INTO diario (usuario_id, fecha, productos, tolerancia, reaccion, sintomas, notas)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, fecha or date.today().isoformat(), json.dumps(productos), int(tolerancia),
             int(reaccion), json.dumps(sintomas or []), notas[:1000]))
        c.commit()
        return cursor.lastrowid


def diario(usuario_id: str, ruta: Path = BASE_DATOS) -> list[dict]:
    with closing(conectar(ruta)) as c:
        filas = c.execute("SELECT * FROM diario WHERE usuario_id = ? ORDER BY fecha DESC, id DESC",
                          (usuario_id,)).fetchall()
    return [{**dict(f), "productos": json.loads(f["productos"]), "sintomas": json.loads(f["sintomas"]),
             "reaccion": bool(f["reaccion"])} for f in filas]


def resumen_journey(usuario_id: str, ruta: Path = BASE_DATOS) -> dict:
    """Lo que Dear Skin "recuerda" de tu piel: qué toleras bien, qué te sentó mal y qué notas."""
    entradas = diario(usuario_id, ruta)
    por_producto: dict[str, list[dict]] = {}
    for e in entradas:
        for p in e["productos"]:
            por_producto.setdefault(p, []).append(e)

    reaccionados, bien_tolerados, seguimiento = [], [], {}
    for p, lista in por_producto.items():
        media = sum(e["tolerancia"] for e in lista) / len(lista)
        reacciones = sum(e["reaccion"] for e in lista)
        fechas = sorted(e["fecha"] for e in lista)
        semanas = (date.fromisoformat(fechas[-1]) - date.fromisoformat(fechas[0])).days // 7
        seguimiento[p] = {"registros": len(lista), "tolerancia_media": round(media, 1),
                          "reacciones": reacciones, "semanas": semanas}
        if reacciones or media <= 2:
            reaccionados.append(p)
        elif len(lista) >= 2 and media >= 4:
            bien_tolerados.append(p)

    sintomas: dict[str, int] = {}
    for e in entradas:
        for s in e["sintomas"]:
            sintomas[s] = sintomas.get(s, 0) + 1
    return {
        "registros": len(entradas),
        "reaccionados": reaccionados,
        "bien_tolerados": bien_tolerados,
        "seguimiento": seguimiento,
        "sintomas_frecuentes": sorted(sintomas, key=lambda s: -sintomas[s])[:3],
        "ultimas_notas": [f"{e['fecha']}: {e['notas']}" for e in entradas[:3] if e["notas"]],
    }


# ---------- Rutinas ----------

def guardar_rutina(usuario_id: str, rutina: dict, ruta: Path = BASE_DATOS) -> int:
    with closing(conectar(ruta)) as c:
        cursor = c.execute("INSERT INTO rutinas (usuario_id, fecha, rutina) VALUES (?, ?, ?)",
                           (usuario_id, _ahora(), json.dumps(rutina, ensure_ascii=False)))
        c.commit()
        return cursor.lastrowid


def ultima_rutina(usuario_id: str, ruta: Path = BASE_DATOS) -> dict | None:
    with closing(conectar(ruta)) as c:
        fila = c.execute("SELECT rutina FROM rutinas WHERE usuario_id = ? ORDER BY id DESC LIMIT 1",
                         (usuario_id,)).fetchone()
    return json.loads(fila["rutina"]) if fila else None


def contexto(usuario_id: str, ruta: Path = BASE_DATOS) -> dict:
    """Todo lo que se sabe del usuario, en un diccionario (lo usa el grafo y el optimizador)."""
    if not usuario_id or not existe(usuario_id, ruta):
        return {"usuario_id": None, "perfil": dict(PERFIL_VACIO), "armario": [],
                "journey": resumen_journey("", ruta), "ultima_rutina": None, "rutina_actual": None}
    return {
        "usuario_id": usuario_id,
        "perfil": obtener_perfil(usuario_id, ruta),
        "armario": armario(usuario_id, ruta),
        "journey": resumen_journey(usuario_id, ruta),
        "ultima_rutina": ultima_rutina(usuario_id, ruta),
        "rutina_actual": rutina_actual(usuario_id, ruta),
    }
