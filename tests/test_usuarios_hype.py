"""Usuarios (perfil, armario, diario) y "¿merece la pena?"."""

from app import hype, usuarios


def test_perfil_armario_diario(bd):
    uid = usuarios.crear_usuario("lu", {"tipo_piel": "seca"}, bd)
    assert usuarios.obtener_perfil(uid, bd)["tipo_piel"] == "seca"
    usuarios.guardar_perfil(uid, {"sensible": True, "evitar": ["perfume"]}, bd)
    perfil = usuarios.obtener_perfil(uid, bd)
    assert perfil["sensible"] and perfil["evitar"] == ["perfume"]

    item = usuarios.anadir_al_armario(uid, "Mi crema de siempre", "hidratante", ruta=bd)
    assert len(usuarios.armario(uid, bd)) == 1
    assert usuarios.quitar_del_armario(uid, item, bd)
    assert usuarios.armario(uid, bd) == []

    usuarios.anotar_diario(uid, ["to-ha-b5"], 5, fecha="2026-10-01", ruta=bd)
    usuarios.anotar_diario(uid, ["to-ha-b5"], 4, fecha="2026-10-22", ruta=bd)
    usuarios.anotar_diario(uid, ["cosrx-aha-bha-toner"], 2, reaccion=True, sintomas=["rojez"],
                           notas="me escuece", fecha="2026-10-22", ruta=bd)
    j = usuarios.resumen_journey(uid, bd)
    assert j["bien_tolerados"] == ["to-ha-b5"] and j["reaccionados"] == ["cosrx-aha-bha-toner"]
    assert j["seguimiento"]["to-ha-b5"]["semanas"] == 3
    assert j["sintomas_frecuentes"] == ["rojez"]


def test_contexto_de_usuario_inexistente(bd):
    ctx = usuarios.contexto("u-nadie", bd)
    assert ctx["usuario_id"] is None and ctx["armario"] == []


CTX = {"perfil": {"tipo_piel": "mixta", "sensible": True, "objetivos": ["acne", "luminosidad"]},
       "armario": [{"id": 1, "producto_id": "boj-glow-serum", "nombre": "", "zona": "cara",
                    "paso": "serum", "activos": []}], "journey": {}}


def test_hype_equivalente_en_casa():
    r = hype.analizar("anua niacinamide txa", CTX)
    assert r["veredicto"] == "ya_tienes_algo_parecido"
    assert "niacinamida" in r["equivalentes"][0]["razon"]
    assert r["alternativas_baratas"][0]["precio"] < r["producto"]["precio"]


def test_hype_poca_evidencia():
    r = hype.analizar("medicube pdrn serum", CTX)
    assert r["encontrado"] and r["evidencia"]["PDRN (polidesoxirribonucleótido)"] == "limited"
    assert r["veredicto"] in {"opcional", "merece_la_pena"}


def test_hype_no_para_ti():
    ctx = {"perfil": {"tipo_piel": "seca", "embarazo": True}}
    assert hype.analizar("the ordinary retinol 0.5", ctx)["veredicto"] == "no_para_ti"


def test_hype_no_encontrado():
    r = hype.analizar("producto inventado xyz", {})
    assert r["encontrado"] is False
