"""Reseñas de usuarios en SQLite.

La web guarda aquí las reseñas (POST /api/resenas) y el agente analista las lee
a través del servidor MCP para contar si un producto funciona a largo plazo y si
da reacciones en tu tipo de piel.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_RESENAS, RESENAS_EJEMPLO

LARGO_PLAZO_SEMANAS = 8   # a partir de aquí consideramos "uso prolongado"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS resenas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id TEXT    NOT NULL,
    alias       TEXT    NOT NULL DEFAULT 'anónimo',
    tipo_piel   TEXT    NOT NULL,
    puntuacion  INTEGER NOT NULL CHECK (puntuacion BETWEEN 1 AND 5),
    semanas_uso INTEGER NOT NULL CHECK (semanas_uso >= 0),
    reaccion    INTEGER NOT NULL DEFAULT 0,
    texto       TEXT    NOT NULL DEFAULT '',
    es_ejemplo  INTEGER NOT NULL DEFAULT 0,
    fecha       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resenas_producto ON resenas(producto_id);
"""


def conectar(ruta: Path = BASE_RESENAS) -> sqlite3.Connection:
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    conexion.executescript(ESQUEMA)
    return conexion


def inicializar(ruta: Path = BASE_RESENAS, con_ejemplos: bool = True) -> None:
    """Crea la tabla y, si está vacía, carga unas reseñas de ejemplo marcadas como tales."""
    with closing(conectar(ruta)) as c:
        vacia = c.execute("SELECT COUNT(*) FROM resenas").fetchone()[0] == 0
        if vacia and con_ejemplos and RESENAS_EJEMPLO.exists():
            for r in json.loads(RESENAS_EJEMPLO.read_text(encoding="utf-8")):
                _insertar(c, {**r, "es_ejemplo": True})
            c.commit()


def _insertar(c: sqlite3.Connection, r: dict) -> int:
    cursor = c.execute(
        "INSERT INTO resenas (producto_id, alias, tipo_piel, puntuacion, semanas_uso, reaccion,"
        " texto, es_ejemplo, fecha) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            r["producto_id"],
            (r.get("alias") or "anónimo").strip()[:40],
            r["tipo_piel"].strip().lower()[:30],
            int(r["puntuacion"]),
            int(r["semanas_uso"]),
            int(bool(r.get("reaccion", False))),
            (r.get("texto") or "").strip()[:1000],
            int(bool(r.get("es_ejemplo", False))),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    return cursor.lastrowid


def guardar_resena(resena: dict, ruta: Path = BASE_RESENAS) -> int:
    with closing(conectar(ruta)) as c:
        nuevo_id = _insertar(c, resena)
        c.commit()
        return nuevo_id


def listar_resenas(producto_id: str, ruta: Path = BASE_RESENAS) -> list[dict]:
    with closing(conectar(ruta)) as c:
        filas = c.execute(
            "SELECT * FROM resenas WHERE producto_id = ? ORDER BY fecha DESC, id DESC",
            (producto_id,),
        ).fetchall()
    return [{**dict(f), "reaccion": bool(f["reaccion"]), "es_ejemplo": bool(f["es_ejemplo"])}
            for f in filas]


def resumenes(tipo_piel: str = "", ruta: Path = BASE_RESENAS) -> dict[str, dict]:
    """Resumen de TODOS los productos con reseñas, en una sola consulta (para el optimizador)."""
    with closing(conectar(ruta)) as c:
        filas = c.execute("SELECT * FROM resenas ORDER BY fecha DESC, id DESC").fetchall()
    por_producto: dict[str, list[dict]] = {}
    for f in filas:
        r = {**dict(f), "reaccion": bool(f["reaccion"]), "es_ejemplo": bool(f["es_ejemplo"])}
        por_producto.setdefault(r["producto_id"], []).append(r)
    return {pid: _resumir(pid, lista, tipo_piel) for pid, lista in por_producto.items()}


def resumen(producto_id: str, tipo_piel: str = "", ruta: Path = BASE_RESENAS) -> dict:
    """Estadísticas de un producto: media, uso prolongado y reacciones (por tipo de piel)."""
    return _resumir(producto_id, listar_resenas(producto_id, ruta), tipo_piel)


def _resumir(producto_id: str, todas: list[dict], tipo_piel: str) -> dict:
    if not todas:
        return {"producto_id": producto_id, "total": 0}

    def media(lista):
        return round(sum(r["puntuacion"] for r in lista) / len(lista), 2) if lista else None

    largo = [r for r in todas if r["semanas_uso"] >= LARGO_PLAZO_SEMANAS]
    mismo_tipo = [r for r in todas if tipo_piel and r["tipo_piel"] == tipo_piel.lower()]
    return {
        "producto_id": producto_id,
        "total": len(todas),
        "media": media(todas),
        "largo_plazo": {"total": len(largo), "media": media(largo)},
        "porcentaje_reacciones": round(100 * sum(r["reaccion"] for r in todas) / len(todas)),
        "tu_tipo_de_piel": {
            "tipo": tipo_piel,
            "total": len(mismo_tipo),
            "media": media(mismo_tipo),
            "reacciones": sum(r["reaccion"] for r in mismo_tipo),
        } if tipo_piel else None,
        "ultimas": [
            {k: r[k] for k in ("tipo_piel", "puntuacion", "semanas_uso", "reaccion", "texto",
                               "es_ejemplo")}
            for r in todas[:3]
        ],
    }
