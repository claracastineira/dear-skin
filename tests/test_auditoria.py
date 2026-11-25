"""Revisor de rutina."""

from app import auditoria

T = ["L", "M", "X", "J", "V", "S", "D"]
CTX = {"perfil": {"tipo_piel": "seca", "sensible": True, "objetivos": ["hidratacion", "antiedad", "manchas"]}}


def paso(*items):
    return {"items": [{"id": i, "dias": d} for i, d in items]}


def test_detecta_errores_clasicos():
    rutina = {
        "manana": [paso(("cerave-limpiador-espumoso", T)), paso(("to-retinol-05", ["L"]))],
        "noche": [paso(("cerave-limpiador-espumoso", T)), paso(("medicube-zero-pore-pad", T)),
                  paso(("to-retinol-05", T))],
    }
    r = auditoria.analizar(rutina, CTX)
    titulos = " | ".join(p["titulo"] for p in r["problemas"])
    assert "a la noche" in titulos                    # retinol de día
    assert "protector solar" in titulos               # falta SPF
    assert "No juntes" in titulos                     # retinol + ácidos la misma noche
    assert "descanso" in titulos and "Exfolias demasiadas" in titulos
    assert r["problemas"][0]["gravedad"] == "alta"
    assert 10 <= r["nota"] < 60
    semana = r["semana_propuesta"]["dias"]
    assert any("exfoliación" in d["tipo"] for d in semana.values())
    assert any("recuperación" in d["tipo"] for d in semana.values())
    # En la semana propuesta, retinol y pads nunca van la misma noche
    for d in semana.values():
        assert not ({"The Ordinary Retinol 0.5% in Squalane", "medicube Zero Pore Pad 2.0"} <= set(d["noche"]))


def test_rutina_buena_saca_buena_nota():
    rutina = {
        "manana": [paso(("cerave-limpiador-hidratante", T)), paso(("cerave-crema-hidratante", T)),
                   paso(("purito-daily-sunscreen", T))],
        "noche": [paso(("heimish-all-clean-balm", T)), paso(("cerave-limpiador-hidratante", T)),
                  paso(("cosrx-retinol-01", ["L", "J"]), ("torriden-dive-in-serum", ["M", "X", "V", "S", "D"])),
                  paso(("cerave-crema-hidratante", T))],
    }
    r = auditoria.analizar(rutina, CTX)
    assert r["nota"] >= 85, r["problemas"]
    assert not [p for p in r["problemas"] if p["gravedad"] != "baja"]
    assert any("protector" in b for b in r["bien"])


def test_productos_del_armario_y_desconocidos():
    ctx = {**CTX, "armario": [{"id": 3, "producto_id": None, "nombre": "Mi crema", "zona": "cara",
                               "paso": "hidratante", "activos": []}]}
    r = auditoria.analizar({"manana": [paso(("armario-3", T)), paso(("no-existe", T))], "noche": []}, ctx)
    assert r["desconocidos"] == ["no-existe"]
    assert any("Mi crema" in x for d in r["semana_propuesta"]["dias"].values() for x in d["manana"])
