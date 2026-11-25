"""Optimizador de rutinas."""

from app import rutina, usuarios


def pasos(r, zona="cara"):
    return [p for seccion in r["zonas"][zona].values() for p in seccion]


def ids(r, zona="cara"):
    return {p["producto"]["id"] for p in pasos(r, zona)}


EJEMPLO = {"zonas": ["cara"], "tipo_piel": "mixta", "sensible": True, "objetivos": ["acne", "luminosidad"],
           "presupuesto": 50, "max_pasos": 4, "ya_tengo": ["hidratante"]}


def test_ejemplo_personal_shopper():
    """Piel mixta y sensible, granitos, quiere luminosidad, ya tiene hidratante, 50 €, sin 10 pasos."""
    r = rutina.optimizar(EJEMPLO, {}, opiniones={})
    assert r["total_compras"] <= 50
    assert all(len(s) <= 4 for s in r["zonas"]["cara"].values())
    assert "propio-hidratante" in ids(r)                         # usa la que ya tiene
    assert all(not c["id"].startswith("propio") for c in r["compras"])
    roles = {p["rol"] for p in pasos(r)}
    assert {"limpiador", "hidratante", "spf"} <= roles
    cubiertos = {o for p in pasos(r) for o in p["producto"].get("objetivos", [])}
    assert {"acne", "luminosidad"} <= cubiertos
    assert any("tolerancia" in a for a in r["avisos"])


def test_protector_solo_por_la_manana():
    r = rutina.optimizar(EJEMPLO, {}, opiniones={})
    assert all(p["rol"] != "spf" for p in r["zonas"]["cara"]["noche"])
    assert any(p["rol"] == "spf" for p in r["zonas"]["cara"]["manana"])


def test_embarazo_sin_retinoides():
    n = {"tipo_piel": "normal", "objetivos": ["antiedad", "textura"], "embarazo": True, "max_pasos": 5}
    r = rutina.optimizar(n, {}, opiniones={})
    activos = {a for p in pasos(r) for a in p["producto"]["activos"]}
    assert not any("retin" in a for a in activos)
    assert any("embarazo" in d["motivo"] for d in r["descartes"])


def test_evitar_ingredientes():
    n = {"tipo_piel": "seca", "objetivos": ["hidratacion"], "evitar_ingredientes": ["perfume", "caracol"]}
    r = rutina.optimizar(n, {}, opiniones={})
    activos = {a for p in pasos(r) for a in p["producto"]["activos"]}
    assert "perfume" not in activos and "baba de caracol" not in activos


def test_retinol_y_acido_en_noches_alternas():
    n = {"tipo_piel": "normal", "objetivos": ["antiedad", "textura"], "max_pasos": 5,
         "fijar_productos": ["to-retinol-05", "to-glycolic-7"]}
    r = rutina.optimizar(n, {}, opiniones={})
    noche = {p["producto"]["id"]: p for p in r["zonas"]["cara"]["noche"]}
    assert {"to-retinol-05", "to-glycolic-7"} <= set(noche)
    assert "alternas" in noche["to-retinol-05"]["frecuencia"]


def test_irritacion_acumulada_en_piel_sensible():
    """En piel sensible no se apilan retinol + ácido + vitamina C pura."""
    n = {"tipo_piel": "normal", "sensible": True, "objetivos": ["antiedad", "manchas", "textura"],
         "max_pasos": 6}
    r = rutina.optimizar(n, {}, opiniones={})
    fuertes = [p for p in r["zonas"]["cara"]["noche"]
               if any(x in " ".join(p["producto"]["activos"]) for x in ("retinol", "AHA", "BHA"))]
    assert len(fuertes) <= 1


def test_presupuesto_compartido_entre_zonas():
    n = {"zonas": ["cara", "cuerpo", "pelo"], "tipo_piel": "seca", "tipo_pelo": "teñido",
         "objetivos": ["antiedad", "brillo", "hidratacion"], "presupuesto": 90, "max_pasos": 4}
    r = rutina.optimizar(n, {}, opiniones={})
    assert set(r["zonas"]) == {"cara", "cuerpo", "pelo"}
    assert r["total_compras"] <= 90


def test_presupuesto_insuficiente_avisa():
    r = rutina.optimizar({"tipo_piel": "normal", "presupuesto": 10}, {}, opiniones={})
    assert r["presupuesto_insuficiente"] and any("no llega" in a for a in r["avisos"])


def test_frio_prefiere_textura_rica():
    base = {"tipo_piel": "normal", "objetivos": ["hidratacion"], "max_pasos": 3}
    frio = rutina.optimizar({**base, "clima": "frio_seco"}, {}, opiniones={})
    hidratante = next(p for p in pasos(frio) if p["rol"] == "hidratante")
    assert any("frío" in m for m in hidratante["motivos"])


def test_armario_y_skin_journey(bd):
    uid = usuarios.crear_usuario("ana", {"tipo_piel": "mixta"}, bd)
    usuarios.anadir_al_armario(uid, "Relief Sun", "spf", producto_id="boj-relief-sun", ruta=bd)
    usuarios.anotar_diario(uid, ["boj-glow-serum"], tolerancia=1, reaccion=True,
                           sintomas=["picor"], ruta=bd)
    ctx = usuarios.contexto(uid, bd)
    r = rutina.optimizar({"tipo_piel": "mixta", "objetivos": ["acne", "luminosidad"], "presupuesto": 60},
                         ctx, opiniones={})
    elegidos = ids(r)
    assert "boj-relief-sun" in elegidos                          # usa el protector que ya tiene
    assert "boj-relief-sun" not in {c["id"] for c in r["compras"]}
    assert r["ahorro_armario"] == 16.0
    assert "boj-glow-serum" not in elegidos                      # le sentó mal


def test_cambios_respecto_a_la_rutina_anterior():
    primera = rutina.optimizar(EJEMPLO, {}, opiniones={})
    segunda = rutina.optimizar({**EJEMPLO, "excluir_productos": [primera["compras"][0]["id"]]},
                               {"ultima_rutina": primera}, opiniones={})
    assert segunda["cambios"]["quita"]
    assert primera["compras"][0]["id"] not in ids(segunda)


def test_alternativas_y_elegir():
    r = rutina.optimizar(EJEMPLO, {}, opiniones={})
    con_opciones = [p for p in pasos(r) if p["alternativas"]]
    assert con_opciones, "algún paso debe ofrecer alternativas"
    for paso in con_opciones:
        for alt in paso["alternativas"]:
            assert r["total_compras"] + alt["diferencia_precio"] <= 50 + 1e-9   # respetan el presupuesto
    alt = con_opciones[0]["alternativas"][0]
    elegida = rutina.optimizar({**EJEMPLO, "fijar_roles": {x: alt["producto"]["id"] for x in alt["roles"]}},
                               {}, opiniones={})
    assert alt["producto"]["id"] in ids(elegida) and elegida["total_compras"] <= 50
    # Si luego lo rechaza en el chat, deja de estar fijado
    rechazada = rutina.optimizar({**elegida["necesidades"], "excluir_productos": [alt["producto"]["id"]]},
                                 {}, opiniones={})
    assert alt["producto"]["id"] not in ids(rechazada)


def test_deseos_y_diez_pasos():
    from app import catalogo
    n = rutina.Necesidades.desde_dict({"objetivos": ["acne"], "deseos": ["glowy", "inventado"], "max_pasos": 14})
    assert n.max_pasos == 10
    assert n.deseos == ["glowy"]
    assert n.objetivos[0] == "acne" and "luminosidad" in n.objetivos
    assert catalogo.paso_y_objetivos("serum_hidratante") == ("serum", ["hidratacion", "barrera"])


def test_serum_hidratante_encima_del_retinol():
    ctx = {"armario": [
        {"id": 1, "producto_id": "to-retinol-05", "nombre": "x", "zona": "cara", "paso": "serum", "activos": [], "momento": "noche"},
        {"id": 2, "producto_id": None, "nombre": "Mi hialurónico", "zona": "cara", "paso": "serum",
         "activos": ["hyaluronic-acid"], "momento": "ambos", "objetivos": ["hidratacion", "barrera"]}]}
    r = rutina.optimizar({"tipo_piel": "seca", "objetivos": ["antiedad"], "max_pasos": 6, "presupuesto": 80}, ctx, opiniones={})
    noche = [p["rol"] for p in r["zonas"]["cara"]["noche"]]
    assert "activo_pm" in noche and "capa_hidratante" in noche
    assert noche.index("activo_pm") < noche.index("capa_hidratante") < noche.index("hidratante")
