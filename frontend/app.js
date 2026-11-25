// Dear Skin · lógica de la web (JavaScript sin dependencias)

const $ = (s, raiz = document) => raiz.querySelector(s);
const $$ = (s, raiz = document) => [...raiz.querySelectorAll(s)];

const OBJETIVOS = {
  cara: { acne: "Granitos", luminosidad: "Luminosidad", manchas: "Manchas", poros: "Poros", grasa: "Exceso de grasa",
          hidratacion: "Hidratación", rojeces: "Rojeces", calmar: "Calmar", barrera: "Reparar la barrera",
          antiedad: "Antiedad", textura: "Textura", ojeras: "Ojeras" },
  cuerpo: { piel_aspera: "Piel áspera", granitos_cuerpo: "Granitos en el cuerpo" },
  pelo: { brillo: "Brillo", reparar: "Reparar el pelo", encrespamiento: "Encrespamiento", caspa: "Caspa",
          cuero_graso: "Cuero cabelludo graso", caida: "Pelo débil", volumen: "Volumen" },
};
// "Cómo quieres tu piel" (mismos ids que catalogo.DESEOS en el servidor)
const DESEOS = { glowy: ["Glowy", "brillo sano, de dentro afuera"], dewy: ["Dewy", "jugosa, acabado húmedo"],
  plumpy: ["Plumpy", "rellena de agua"], bouncy: ["Bouncy", "elástica, que rebota"], clear: ["Clear", "sin granitos ni puntos negros"],
  hidratada: ["Hidratada", ""], smooth: ["Smooth", "lisa al tacto"], suave: ["Suave", ""], menos_textura: ["Menos textura", ""],
  poros: ["Poros menos visibles", ""], menos_grasa: ["Menos grasa", ""], mate: ["Mate", "sin brillos"],
  uniforme: ["Tono uniforme", "sin manchas ni marcas"], luminosa: ["Luminosa", "bright, nada apagada"], radiante: ["Radiante", ""],
  fresca: ["Fresca", "ligera, nada pesada"], firme: ["Firme", ""], calmada: ["Calmada", ""], menos_rojeces: ["Menos rojeces", ""],
  sana: ["Sana", "barrera fuerte"] };

// Orden de cabina: limpieza -> tónico -> sérums (tratamiento antes que hidratante) -> crema -> SPF
const SUBTIPO_SERUM = { serum_hidratante: "hidratante", serum_tratamiento: "tratamiento", serum_antiedad: "antiedad",
  serum_smooth: "textura", serum_luminosidad: "luminosidad", serum_calmante: "calmante" };
function categoriaPaso(p) {
  const paso = p.paso || "", obj = new Set(p.objetivos || []);
  if (paso === "limpiador_aceite") return { orden: 0, etiqueta: "Limpieza · desmaquillante" };
  if (paso === "limpiador") return { orden: 1, etiqueta: "Limpieza · gel o espuma" };
  if (paso === "tonico" || paso === "esencia") return { orden: 2, etiqueta: paso === "esencia" ? "Esencia" : "Tónico" };
  if (["serum", "tratamiento", "puntual", "mascarilla"].includes(paso)) {
    let tipo = SUBTIPO_SERUM[p.subtipo];
    if (!tipo) {
      if (["acne", "poros", "grasa"].some((o) => obj.has(o))) tipo = "tratamiento";
      else if (obj.has("antiedad")) tipo = "antiedad";
      else if (obj.has("textura")) tipo = "textura";
      else if (obj.has("manchas") || obj.has("luminosidad")) tipo = "luminosidad";
      else if (obj.has("rojeces") || obj.has("calmar")) tipo = "calmante";
      else tipo = "hidratante";
    }
    // Los activos van primero, pegados a la piel; el hidratante encima para compensar
    return { orden: tipo === "hidratante" ? 4 : tipo === "calmante" ? 3.5 : 3, etiqueta: `Sérum · ${tipo}` };
  }
  if (paso === "contorno") return { orden: 5, etiqueta: "Contorno de ojos" };
  if (paso === "hidratante") return { orden: 6, etiqueta: "Crema" };
  if (paso === "spf") return { orden: 7, etiqueta: "Protector solar" };
  return { orden: 5, etiqueta: paso.replaceAll("_", " ") };
}

const SECCIONES = { manana: "Mañana", noche: "Noche", ducha: "En la ducha", despues: "Después de la ducha",
                    lavado: "Lavado", acabado: "Acabado" };
const ZONAS = { cara: "Cara", cuerpo: "Cuerpo", pelo: "Pelo" };
const VEREDICTOS = { merece_la_pena: "Sí, puede aportarte algo", ya_tienes_algo_parecido: "Ya tienes algo que hace lo mismo",
                     ya_lo_tienes: "Ya lo tienes", opcional: "Capricho opcional", no_para_ti: "No es para tu piel" };

const estado = { usuarioId: leer("dearskin-usuario") || leer("tez-usuario"), sesionId: null, perfil: null,
                 armario: [], rutina: null, nombres: {}, productos: {}, objetivosElegidos: [],
                 rutinaActual: { manana: [], noche: [] } };

// ---------- Utilidades ----------

function leer(clave) { try { return localStorage.getItem(clave); } catch { return null; } }
function guardar(clave, valor) { try { valor ? localStorage.setItem(clave, valor) : localStorage.removeItem(clave); } catch { /* sin almacenamiento */ } }

function escapar(t) {
  return String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const euros = (n) => `${Number(n || 0).toFixed(2).replace(".", ",")} €`;

async function api(ruta, opciones = {}) {
  const res = await fetch(ruta, {
    ...opciones,
    headers: { "Content-Type": "application/json" },
    body: opciones.body ? JSON.stringify(opciones.body) : undefined,
  });
  const datos = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detalle = datos?.detail;
    throw new Error(typeof detalle === "string" ? detalle : `Error ${res.status}`);
  }
  return datos;
}

function enLinea(t) {
  return escapar(t).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<em>$2</em>");
}
function markdown(texto) {
  const html = []; let lista = null;
  const cerrar = () => { if (lista) { html.push(`</${lista}>`); lista = null; } };
  for (const linea of texto.replace(/<br\s*\/?>/gi, " · ").split("\n")) {
    let l = linea.trim(); let m;
    if (/^\|?\s*:?-{3,}/.test(l)) continue;                               // separador de tabla
    if (l.startsWith("|")) l = "- " + l.split("|").map((c) => c.trim()).filter(Boolean).join(" · ");
    if (!l) { cerrar(); continue; }
    if ((m = l.match(/^#{1,6}\s+(.*)/))) { cerrar(); html.push(`<h3>${enLinea(m[1])}</h3>`); continue; }
    if ((m = l.match(/^[-*•]\s+(.*)/)) || (m = l.match(/^\d+[.)]\s+(.*)/))) {
      const tipo = /^\d/.test(l) ? "ol" : "ul";
      if (lista !== tipo) { cerrar(); html.push(`<${tipo}>`); lista = tipo; }
      html.push(`<li>${enLinea(m[1])}</li>`); continue;
    }
    cerrar(); html.push(`<p>${enLinea(l)}</p>`);
  }
  cerrar();
  return html.join("");
}

// ---------- Pestañas ----------

function irA(nombre) {
  $$(".pestanas [role=tab]").forEach((b) => {
    const activa = b.id === `tab-${nombre}`;
    b.setAttribute("aria-selected", activa);
    $(`#${b.getAttribute("aria-controls")}`).hidden = !activa;
  });
  if (nombre === "journey") pintarProductosDiario();
}
$(".pestanas").addEventListener("click", (e) => {
  const b = e.target.closest("[role=tab]");
  if (b) irA(b.id.replace("tab-", ""));
});

// ---------- Componentes ----------

const PASTELES = ["#fde2da", "#fbd3c7", "#f9e4d4", "#f4dde7", "#fcebd9", "#f7d9de"];
const TAPAS = ["#f08a75", "#e9a28f", "#d98c8c", "#c9553f", "#eab09a", "#e48b97"];

function hash(t) { let h = 0; for (const c of String(t)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }

// Ilustración del envase según el tipo de producto (cuando no hay foto real)
function ilustracion(p) {
  const h = hash(p.id || p.nombre), fondo = PASTELES[h % PASTELES.length], tapa = TAPAS[(h >>> 3) % TAPAS.length];
  const inicial = escapar(((p.marca || p.nombre || "?").trim()[0] || "?").toUpperCase());
  const paso = p.paso || "";
  let envase;
  if (["serum", "esencia", "contorno", "tratamiento", "cuero_cabelludo", "tratamiento_capilar", "puntual"].includes(paso)) {
    envase = `<rect x="36" y="44" width="28" height="48" rx="6" fill="#fff"/><rect x="42" y="34" width="16" height="12" rx="2" fill="${tapa}"/><ellipse cx="50" cy="26" rx="7" ry="9" fill="${tapa}"/>`;
  } else if (["hidratante", "mascarilla", "mascarilla_capilar", "tratamiento_corporal"].includes(paso)) {
    envase = `<rect x="26" y="58" width="48" height="32" rx="10" fill="#fff"/><rect x="24" y="46" width="52" height="15" rx="6" fill="${tapa}"/>`;
  } else if (["spf", "limpiador"].includes(paso)) {
    envase = `<path d="M34 30 h32 l-4 52 q-12 6 -24 0 z" fill="#fff"/><rect x="40" y="82" width="20" height="10" rx="3" fill="${tapa}"/>`;
  } else {
    envase = `<rect x="33" y="42" width="34" height="50" rx="9" fill="#fff"/><rect x="45" y="30" width="10" height="13" fill="${tapa}"/><rect x="45" y="26" width="20" height="5" rx="2" fill="${tapa}"/>`;
  }
  return `<svg viewBox="0 0 100 100" aria-hidden="true"><rect width="100" height="100" fill="${fondo}"/>
    <ellipse cx="50" cy="93" rx="26" ry="3" fill="#c9553f" fill-opacity=".12"/>${envase}
    <text x="50" y="76" text-anchor="middle" font-family="Instrument Serif, serif" font-size="15" fill="#c9553f">${inicial}</text></svg>`;
}

function foto(p, clase = "") {
  const img = p.imagen ? `<img src="${escapar(p.imagen)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
  return `<div class="foto ${clase}" role="img" aria-label="${escapar([p.marca, p.nombre].filter(Boolean).join(" "))}">${ilustracion(p)}${img}</div>`;
}

function comprarHTML(enlaces) {
  if (!enlaces?.length) return "";
  return `<p class="comprar-en"><span>Comprar en</span>${enlaces.map((e) =>
    `<a href="${escapar(e.url)}" target="_blank" rel="noopener" title="${escapar(e.tipo || "")}">${escapar(e.tienda)}</a>`).join("")}</p>`;
}

// "baba de caracol: hidrata..." -> no repetir el nombre que ya va en negrita
function sinRepetir(nombre, texto) {
  const i = texto.indexOf(": ");
  if (i < 0) return texto;
  const prefijo = texto.slice(0, i).toLowerCase(), n = nombre.toLowerCase();
  const repetido = n.includes(prefijo) || prefijo.includes(n.split(" (")[0]) || prefijo.includes(n.split(" ")[0]);
  return repetido ? texto.slice(i + 2) : texto;
}

function queLleva(p, max = 4) {
  const lista = (p.ingredientes || []).filter((i) => i.que_hace).slice(0, max);
  return lista.length ? `<ul class="que-lleva">${lista.map((i) => `<li><b>${escapar(i.nombre)}</b>: ${escapar(sinRepetir(i.nombre, i.que_hace))}</li>`).join("")}</ul>` : "";
}

function tarjetaProducto(p) {
  const r = p.resenas || { total: 0 };
  const valoracion = r.total ? `★ ${r.media.toFixed(1)} · ${r.total} reseña${r.total === 1 ? "" : "s"}` : "";
  return `
    <article class="producto">
      ${foto(p, "grande")}
      <p class="marca">${escapar(p.marca)}${p.origen === "kr" ? " · K-beauty" : ""}</p>
      <h3>${escapar(p.nombre)}</h3>
      <p class="precio">${p.ya_lo_tienes ? '<span class="ya-tienes">Ya lo tienes: úsalo</span>' : (p.precio ? "≈ " + euros(p.precio) : "Precio no disponible")} <small>${escapar(p.tamano || "")}</small></p>
      <p class="descripcion">${escapar(p.descripcion || "")}</p>
      ${queLleva(p, 3)}
      ${valoracion ? `<p class="valoracion">${valoracion}</p>` : ""}
      ${comprarHTML(p.enlaces)}
      <div class="acciones">
        <button class="boton-secundario" type="button" data-elegir="${escapar(p.marca + " " + p.nombre)}">Elegir este</button>
        <button class="enlace" type="button" data-armario="${p.id}">Lo tengo</button>
        <button class="enlace" type="button" data-ver="${p.id}">Reseñas</button>
      </div>
    </article>`;
}

// ---------- Rutina ----------

function opcionHTML(o) {
  const p = o.producto, d = o.diferencia_precio;
  const dif = d === 0 ? "mismo precio" : `${d > 0 ? "+" : "−"}${euros(Math.abs(d))}`;
  return `<div class="opcion">
    ${foto(p, "mini")}
    <div><h5>${escapar(p.marca)} · ${escapar(p.nombre)}</h5>
      <p><span class="precio-dif">${p.precio ? euros(p.precio) : ""} (${dif})</span> · ${escapar(o.motivos.slice(0, 2).join(" · "))}</p></div>
    <button class="boton-secundario" type="button" data-opcion="${p.id}" data-roles="${o.roles.join(",")}">Elegir esta</button>
  </div>`;
}

function pasoHTML(paso) {
  const p = paso.producto;
  const esCatalogo = !p.id.startsWith("propio-") && !p.id.startsWith("armario-");
  const precio = paso.ya_lo_tienes ? `<span class="ya-tienes">Ya lo tienes</span>` : (p.precio ? `≈ ${euros(p.precio)}` : "");
  const porque = paso.motivos?.length ? `<ul class="motivos">${paso.motivos.map((m) => `<li>${escapar(m)}</li>`).join("")}</ul>` : "";
  const alternativas = paso.alternativas || [];
  return `
    <li class="paso-rutina">
      <div class="cabeza-paso">
        ${foto(p)}
        <div>
          <p class="numero-rol">${escapar(paso.rol_nombre)}</p>
          <h4>${escapar(p.nombre)}</h4>
          ${p.marca ? `<p class="marca">${escapar(p.marca)}${p.origen === "kr" ? " · K-beauty" : ""}</p>` : ""}
          <p class="meta">${precio}${p.tamano ? ` · ${escapar(p.tamano)}` : ""}<span class="frecuencia">${escapar(paso.frecuencia)}</span></p>
        </div>
      </div>
      <div class="explicacion">
        ${p.descripcion ? `<p>${escapar(p.descripcion)}</p>` : ""}
        ${porque ? `<p class="titulo">Por qué es para ti</p>${porque}` : ""}
        ${(p.ingredientes || []).some((i) => i.que_hace) ? `<p class="titulo">Qué lleva</p>${queLleva(p)}` : ""}
      </div>
      ${esCatalogo && !paso.ya_lo_tienes ? comprarHTML(p.enlaces) : ""}
      ${esCatalogo ? `<div class="acciones">
        <button class="enlace" type="button" data-ver="${p.id}">Reseñas</button>
        ${paso.ya_lo_tienes ? "" : `<button class="enlace" type="button" data-armario="${p.id}">Ya lo tengo</button>`}
        <button class="enlace" type="button" data-cambiar="${escapar(p.marca + " " + p.nombre)}">Pedir otro en el chat</button>
      </div>` : ""}
      ${alternativas.length ? `<details class="opciones"><summary>Ver ${alternativas.length > 1 ? `${alternativas.length} opciones más que también te encajan` : "1 opción más que también te encaja"}</summary>
        <div class="lista-opciones">${alternativas.map(opcionHTML).join("")}</div></details>` : ""}
    </li>`;
}

function pintarRutina(r) {
  estado.rutina = r;
  if (!r) return;
  const n = r.necesidades;
  let bloques = "";
  for (const [zona, secciones] of Object.entries(r.zonas)) {
    for (const [seccion, pasos] of Object.entries(secciones)) {
      bloques += `<section class="momento"><h3>${SECCIONES[seccion]}${zona !== "cara" ? `<span class="zona">${ZONAS[zona]}</span>` : ""}</h3>
        <ol class="pasos-rutina">${pasos.map(pasoHTML).join("")}</ol></section>`;
    }
  }
  const compras = r.compras.length
    ? `<ul class="compras">${r.compras.map((c) => `<li>${foto(c, "mini")}<span>${escapar(c.marca)} · ${escapar(c.nombre)}</span><span>${euros(c.precio)}</span></li>`).join("")}</ul>`
    : `<p>No necesitas comprar nada: todo sale de tu armario.</p>`;
  const extra = [
    `<section class="bloque"><h3>Lo que tienes que comprar</h3>${compras}
      <p class="total"><span>Total</span><span>${euros(r.total_compras)}${r.presupuesto ? ` de ${euros(r.presupuesto)}` : ""}</span></p>
      ${r.ahorro_armario ? `<p>Te ahorras ${euros(r.ahorro_armario)} usando lo que ya tienes.</p>` : ""}</section>`,
    r.plan_introduccion.length ? `<section class="bloque"><h3>Cómo empezar</h3><ol>${r.plan_introduccion.map((p) => `<li>${escapar(p)}</li>`).join("")}</ol>
      <p class="ayuda">Un producto nuevo cada semana: así, si algo no te sienta bien, sabrás cuál es.</p></section>` : "",
    r.avisos.length ? `<section class="bloque alerta"><h3>Ten en cuenta</h3><ul>${r.avisos.map((a) => `<li>${escapar(a)}</li>`).join("")}</ul></section>` : "",
    r.cambios ? `<section class="bloque cambios"><h3>Cambios respecto a tu rutina anterior</h3>
      <p><b>Entra:</b> ${escapar(r.cambios.anade.join(", ") || "nada")}</p><p><b>Sale:</b> ${escapar(r.cambios.quita.join(", ") || "nada")}</p></section>` : "",
    r.descartes.length ? `<section class="bloque"><details><summary class="enlace">Lo que he descartado y por qué</summary>
      <ul>${r.descartes.map((d) => `<li>${escapar(d.producto)}: ${escapar(d.motivo)}</li>`).join("")}</ul></details></section>` : "",
  ].join("");
  const resumen = `<p class="entendido">He entendido: piel ${escapar(n.tipo_piel)}${n.sensible ? " y sensible" : ""} · ${n.objetivos.map((o) => escapar(nombreObjetivo(o).toLowerCase())).join(", ") || "sin objetivos concretos"}${n.presupuesto ? ` · ${euros(n.presupuesto)}` : ""} · máximo ${n.max_pasos} pasos${n.clima ? " · ajustada al clima" : ""}</p>`;
  $("#rutina-completa").innerHTML = `${resumen}<div class="rutina-zonas">${bloques}</div><div class="rutina-extra">${extra}</div>`;

  $("#rutina-mini").innerHTML = Object.entries(r.zonas).map(([zona, secciones]) =>
    Object.entries(secciones).map(([seccion, pasos]) => `<div class="mini-seccion"><h3>${SECCIONES[seccion]}${zona !== "cara" ? ` · ${ZONAS[zona]}` : ""}</h3>
      <ol>${pasos.map((p) => `<li>${foto(p.producto, "mini")}<span>${escapar(p.producto.nombre)}${p.ya_lo_tienes ? " · ya lo tienes" : ""}</span></li>`).join("")}</ol></div>`).join("")).join("")
    + `<p class="mini-total">A comprar: ${euros(r.total_compras)}${r.presupuesto ? ` de ${euros(r.presupuesto)}` : ""}</p>
       <button class="enlace" type="button" data-ir="rutina">Ver la rutina completa y dónde comprar</button>`;
  pintarProductosDiario();
}

function nombreObjetivo(o) {
  for (const grupo of Object.values(OBJETIVOS)) if (grupo[o]) return grupo[o];
  return o;
}

function pintarChipsObjetivos() {
  const todos = { ...OBJETIVOS.cara, ...OBJETIVOS.cuerpo, ...OBJETIVOS.pelo };
  $("#chips-objetivos").innerHTML = Object.entries(todos).map(([id, nombre]) =>
    `<label><input type="checkbox" value="${id}" data-objetivo><span>${nombre}<span class="orden"></span></span></label>`).join("");
}
$("#chips-objetivos").addEventListener("change", (e) => {
  const id = e.target.value;
  estado.objetivosElegidos = e.target.checked ? [...estado.objetivosElegidos, id] : estado.objetivosElegidos.filter((o) => o !== id);
  $$("[data-objetivo]").forEach((c) => {
    const i = estado.objetivosElegidos.indexOf(c.value);
    c.nextElementSibling.querySelector(".orden").textContent = i >= 0 ? i + 1 : "";
  });
});

$("#formulario-rutina").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const necesidades = {
    zonas: $$("input[name=zonas]:checked", f).map((c) => c.value),
    ...(estado.objetivosElegidos.length ? { objetivos: estado.objetivosElegidos } : {}),
    presupuesto: f.presupuesto.value ? Number(f.presupuesto.value) : null,
    max_pasos: f.max_pasos.value ? Number(f.max_pasos.value) : null,
    clima: f.clima.value,
  };
  const boton = $("button[type=submit]", f);
  boton.disabled = true;
  try {
    pintarRutina(await api("/api/rutina", { method: "POST", body: { usuario_id: estado.usuarioId, necesidades } }));
    f.closest("details").open = false;
  } catch (error) {
    $("#rutina-completa").innerHTML = `<p class="estado-formulario mal">${escapar(error.message)}</p>`;
  } finally { boton.disabled = false; }
});

async function elegirOpcion(productoId, roles, boton) {
  if (!estado.rutina) return;
  boton.disabled = true; boton.textContent = "Recalculando…";
  try {
    pintarRutina(await api("/api/rutina/elegir", { method: "POST", body: {
      usuario_id: estado.usuarioId, necesidades: estado.rutina.necesidades, producto_id: productoId, roles } }));
  } catch (error) { boton.disabled = false; boton.textContent = "Elegir esta"; alert(error.message); }
}

// ---------- Revisar mi rutina ----------

const DIAS = ["L", "M", "X", "J", "V", "S", "D"];
const NOMBRE_DIA = { L: "Lunes", M: "Martes", X: "Miércoles", J: "Jueves", V: "Viernes", S: "Sábado", D: "Domingo" };

function datosItem(id) {
  if (estado.productos[id]) return estado.productos[id];
  const a = estado.armario.find((x) => `armario-${x.id}` === id);
  return a ? { id, nombre: a.nombre, marca: "", paso: a.paso, subtipo: a.subtipo, objetivos: a.objetivos }
           : { id, nombre: id, marca: "", paso: "" };
}

function pintarConstructor() {
  for (const momento of ["manana", "noche"]) {
    const lista = $(`.columna-rutina[data-momento="${momento}"] .pasos-constructor`);
    const pasos = estado.rutinaActual[momento];
    lista.innerHTML = pasos.length ? pasos.map((paso, i) => `
      <li class="paso-constructor">
        <p class="categoria-paso">${escapar(categoriaPaso(datosItem(paso.items[0].id)).etiqueta)}</p>
        <div class="numero"><span class="mover">
          <button type="button" data-mover="${momento}:${i}:-1" aria-label="Subir">↑</button>
          <button type="button" data-mover="${momento}:${i}:1" aria-label="Bajar">↓</button></span></div>
        ${paso.items.map((it, j) => {
          const p = datosItem(it.id);
          return `<div class="item-constructor">${foto(p, "mini")}
            <div><p>${escapar([p.marca, p.nombre].filter(Boolean).join(" · "))}</p>
              <div class="dias" role="group" aria-label="Días">${DIAS.map((d) =>
                `<button type="button" aria-pressed="${it.dias.includes(d)}" data-dia="${momento}:${i}:${j}:${d}" title="${NOMBRE_DIA[d]}">${d}</button>`).join("")}</div></div>
            <button class="quitar" type="button" data-quitar-item="${momento}:${i}:${j}" aria-label="Quitar">×</button></div>`;
        }).join("")}
        ${paso.items.length < 2 ? `<button class="enlace" type="button" data-alternar="${momento}:${i}">＋ Alternar con otro producto</button>` : ""}
      </li>`).join("") : `<li class="vacio">Aún no has añadido nada.</li>`;
  }
  try { localStorage.setItem("dearskin-rutina-actual", JSON.stringify(estado.rutinaActual)); } catch { /* sin almacenamiento */ }
}

let destinoAlternar = null;   // {momento, i} cuando se busca el 2º producto de un paso
function anadirAlConstructor(momento, id) {
  if (destinoAlternar && destinoAlternar.momento === momento) {
    const paso = estado.rutinaActual[momento][destinoAlternar.i];
    paso.items[0].dias = ["L", "X", "V", "D"];
    paso.items.push({ id, dias: ["M", "J", "S"] });
    destinoAlternar = null;
    $(`#buscar-${momento}`).placeholder = "＋ Añade un producto (busca o elige de tu armario)";
  } else {
    // Se coloca en su sitio: limpieza, tónico, sérums, crema y protector solar
    const lista = estado.rutinaActual[momento];
    const orden = categoriaPaso(datosItem(id)).orden;
    const sitio = lista.findIndex((paso) => categoriaPaso(datosItem(paso.items[0].id)).orden > orden);
    lista.splice(sitio < 0 ? lista.length : sitio, 0, { items: [{ id, dias: [...DIAS] }] });
  }
  pintarConstructor();
}

function buscadorConstructor(momento) {
  const entrada = $(`#buscar-${momento}`), lista = entrada.nextElementSibling;
  let t;
  const pintar = async () => {
    const q = entrada.value.trim().toLowerCase();
    const delArmario = estado.armario.filter((a) => !q || a.nombre.toLowerCase().includes(q)).slice(0, 6)
      .map((a) => ({ ...(estado.productos[a.producto_id] || { nombre: a.nombre, marca: "", paso: a.paso, subtipo: a.subtipo, objetivos: a.objetivos }), id: a.producto_id || `armario-${a.id}`, armario: true }));
    let delCatalogo = [];
    if (q.length >= 3) {
      delCatalogo = (await api(`/api/productos?q=${encodeURIComponent(q)}&limite=6`)).filter((p) => !delArmario.some((a) => a.id === p.id));
      delCatalogo.forEach((p) => { estado.productos[p.id] = p; });
    }
    const todos = [...delArmario, ...delCatalogo];
    lista.innerHTML = todos.map((p) => `<li><button type="button" data-anadir="${momento}:${escapar(p.id)}">${foto(p, "mini")}
      <span>${escapar([p.marca, p.nombre].filter(Boolean).join(" · "))}</span>${p.armario ? '<span class="etiqueta-armario">tu armario</span>' : ""}</button></li>`).join("");
  };
  entrada.addEventListener("focus", pintar);
  entrada.addEventListener("input", () => { clearTimeout(t); t = setTimeout(pintar, 250); });
}
buscadorConstructor("manana"); buscadorConstructor("noche");

function pintarInforme(r) {
  const cont = $("#informe-revision");
  const grav = { alta: "Importante", media: "Mejorable", baja: "Detalle" };
  const sem = r.semana_propuesta;
  cont.innerHTML = `<div class="informe">
    <div class="cabeza-informe"><p class="nota">${r.nota}<small>/100</small></p>
      <div><h3>${r.nota >= 85 ? "Tu rutina está muy bien" : r.nota >= 60 ? "Va bien, con algunos ajustes" : "Hay cosas importantes que cambiar"}</h3>
      ${r.objetivos_sin_cubrir.length ? `<p class="ayuda">Nadie trabaja: ${r.objetivos_sin_cubrir.map(escapar).join(", ")}.</p>` : ""}</div></div>
    ${r.bien.length ? `<section class="bloque"><h3>Lo que haces bien</h3><ul>${r.bien.map((b) => `<li>${escapar(b)}</li>`).join("")}</ul></section>` : ""}
    ${r.problemas.length ? `<section><h3 class="titulo-seccion">Qué cambiar</h3><ul class="problemas">${r.problemas.map((p) => `
      <li class="problema ${p.gravedad}"><h4>${escapar(p.titulo)}<span class="etiqueta-gravedad">${grav[p.gravedad]}</span></h4>
        ${p.cuando ? `<p class="cuando">Cuándo: ${escapar(p.cuando)}</p>` : ""}<p>${escapar(p.detalle)}</p></li>`).join("")}</ul></section>` : ""}
    ${r.sobran.length ? `<section class="bloque"><h3>Te sobra o aporta poco</h3><ul>${r.sobran.map((s) => `<li><b>${escapar(s.producto)}</b>: ${escapar(s.motivo)}</li>`).join("")}</ul></section>` : ""}
    <section class="bloque"><h3>Orden correcto</h3>
      <p><b>Mañana:</b> ${r.orden_correcto.manana.map(escapar).join(" → ") || "—"}</p>
      <p><b>Noche:</b> ${r.orden_correcto.noche.map(escapar).join(" → ") || "—"}</p></section>
    <section><h3 class="titulo-seccion">Tu semana propuesta</h3><p class="ayuda">${escapar(sem.explicacion)}</p>
      <div class="semana">${DIAS.map((d) => { const x = sem.dias[d]; const clase = x.tipo.includes("exfol") ? "exfoliacion" : x.tipo.includes("retino") ? "retinoide" : x.tipo.includes("recuper") ? "recuperacion" : "";
        return `<div class="dia"><h4>${NOMBRE_DIA[d]}</h4><span class="tipo-noche ${clase}">${escapar(x.tipo)}</span>
          <p>Mañana</p><ul>${x.manana.map((n) => `<li>${escapar(n)}</li>`).join("")}</ul>
          <p>Noche</p><ul>${x.noche.map((n) => `<li>${escapar(n)}</li>`).join("")}</ul></div>`; }).join("")}</div>
      <p class="centrado"><button class="boton-secundario" type="button" id="usar-semana">Usar esta semana como mi rutina</button></p></section>
    ${r.alternativas.length ? `<section><h3 class="titulo-seccion">Mejores alternativas</h3>${r.alternativas.map((a) => `
      <p class="ayuda">Para ${escapar(a.para)} (${escapar(a.motivo)}):</p>
      <div class="productos">${a.opciones.map((p) => tarjetaProducto({ ...p, resenas: { total: 0 } })).join("")}</div>`).join("")}</section>` : ""}
  </div>`;
  estado.ultimaRevision = r;
  cont.scrollIntoView({ behavior: "smooth", block: "start" });
}

$("#boton-revisar").addEventListener("click", async (e) => {
  const total = estado.rutinaActual.manana.length + estado.rutinaActual.noche.length;
  if (!total) { $("#informe-revision").innerHTML = `<p class="estado-formulario mal">Añade al menos un producto a tu mañana o tu noche.</p>`; return; }
  e.target.disabled = true; e.target.textContent = "Revisando…";
  try {
    pintarInforme(await api("/api/revisar", { method: "POST", body: { usuario_id: estado.usuarioId, rutina: estado.rutinaActual,
      perfil: estado.perfil ? {} : { sensible: false } } }));
  } catch (error) { $("#informe-revision").innerHTML = `<p class="estado-formulario mal">${escapar(error.message)}</p>`; }
  finally { e.target.disabled = false; e.target.textContent = "Revisar mi rutina"; }
});

function semanaARutina(sem) {
  const nueva = { manana: [], noche: [] };
  for (const momento of ["manana", "noche"]) {
    const dias = {};
    DIAS.forEach((d) => (sem.dias[d].ids[momento] || []).forEach((id) => { (dias[id] ||= []).push(d); }));
    nueva[momento] = Object.entries(dias).map(([id, ds]) => ({ items: [{ id, dias: ds }] }));
  }
  return nueva;
}

// ---------- Chat ----------

const mensajes = $("#mensajes"), entrada = $("#entrada"), botonEnviar = $("#enviar");

function anadirMensaje(quien, html) {
  const li = document.createElement("li");
  li.className = `mensaje ${quien}`;
  li.innerHTML = `<div class="burbuja">${html}</div>`;
  mensajes.append(li);
  mensajes.scrollTop = mensajes.scrollHeight;
  return li;
}

async function enviar(texto) {
  irA("asistente");
  anadirMensaje("usuario", escapar(texto));
  $("#sugerencias").hidden = true;
  botonEnviar.disabled = true;
  const pensando = anadirMensaje("bot pensando", '<span class="gota"></span><span class="gota"></span><span class="gota"></span>');
  pensando.setAttribute("aria-label", "Dear Skin está pensando");
  try {
    const d = await api("/api/chat", { method: "POST", body: { mensaje: texto, usuario_id: estado.usuarioId, sesion_id: estado.sesionId } });
    estado.sesionId = d.sesion_id;
    pensando.remove();
    let html = markdown(d.respuesta);
    if (d.rutina) {
      pintarRutina(d.rutina);
      html += `<p class="aviso-rutina"><button class="boton-secundario" type="button" data-ir="rutina">Ver mi rutina paso a paso</button></p>`;
    }
    if (d.revision) {
      pintarInforme(d.revision); irA("asistente");
      html += `<p class="aviso-rutina"><button class="boton-secundario" type="button" data-ir="revisar">Ver la revisión completa</button></p>`;
    }
    if (d.hype?.encontrado) html += `<div class="productos">${tarjetaProducto({ ...d.hype.producto, resenas: { total: 0 } })}</div>`;
    if (d.productos.length) html += `<div class="productos">${d.productos.map(tarjetaProducto).join("")}</div>`;
    const li = anadirMensaje("bot", html);
    if (d.pasos.length) li.insertAdjacentHTML("beforeend",
      `<details class="pasos"><summary>Cómo lo he pensado</summary><ol>${d.pasos.map((p) => `<li>${escapar(p)}</li>`).join("")}</ol></details>`);
  } catch (error) {
    pensando.remove();
    anadirMensaje("bot error", `<p>${escapar(error.message)}</p><p>Si es un error 429, espera unos segundos y vuelve a enviarlo.</p>`);
  } finally {
    botonEnviar.disabled = false;
    entrada.focus();
  }
}

$("#formulario-chat").addEventListener("submit", (e) => {
  e.preventDefault();
  const texto = entrada.value.trim();
  if (!texto || botonEnviar.disabled) return;
  entrada.value = ""; ajustarAltura(); enviar(texto);
});
entrada.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#formulario-chat").requestSubmit(); }
});
function ajustarAltura() { entrada.style.height = "auto"; entrada.style.height = `${entrada.scrollHeight}px`; }
entrada.addEventListener("input", ajustarAltura);
$("#sugerencias").addEventListener("click", (e) => { if (e.target.matches("button")) enviar(e.target.textContent); });

// ---------- Usuario y perfil ----------

let objetivosPerfil = [];
function pintarChipsPerfil() {
  $("#perfil-objetivos").innerHTML = Object.entries(OBJETIVOS.cara).map(([id, nombre]) => {
    const i = objetivosPerfil.indexOf(id);
    return `<label><input type="checkbox" value="${id}" data-objetivo-perfil ${i >= 0 ? "checked" : ""}><span>${nombre}<span class="orden">${i >= 0 ? i + 1 : ""}</span></span></label>`;
  }).join("");
  const deseos = new Set(estado.perfil?.deseos || []);
  $("#perfil-deseos").innerHTML = Object.entries(DESEOS).map(([id, [nombre, ayuda]]) =>
    `<label${ayuda ? ` title="${escapar(ayuda)}"` : ""}><input type="checkbox" name="deseos" value="${id}" ${deseos.has(id) ? "checked" : ""}><span>${nombre}${ayuda ? `<small class="ayuda-chip"> · ${escapar(ayuda)}</small>` : ""}</span></label>`).join("");
}
$("#perfil-objetivos").addEventListener("change", (e) => {
  const id = e.target.value;
  objetivosPerfil = e.target.checked ? [...objetivosPerfil, id] : objetivosPerfil.filter((o) => o !== id);
  $$("[data-objetivo-perfil]").forEach((c) => {
    const i = objetivosPerfil.indexOf(c.value);
    c.nextElementSibling.querySelector(".orden").textContent = i >= 0 ? i + 1 : "";
  });
});

async function refrescarUsuario() {
  if (!estado.usuarioId) { pintarUsuario(); return; }
  try {
    const d = await api(`/api/usuarios/${estado.usuarioId}`);
    estado.perfil = d.perfil; estado.armario = d.armario;
    pintarUsuario(); pintarArmario(); pintarJourney(d.journey, d.diario);
    if (d.ultima_rutina) pintarRutina(d.ultima_rutina);
    if (d.rutina_actual && (d.rutina_actual.manana?.length || d.rutina_actual.noche?.length)) {
      estado.rutinaActual = d.rutina_actual; pintarConstructor();
    }
  } catch {
    estado.usuarioId = null; guardar("dearskin-usuario", null); pintarUsuario();
  }
}

function pintarUsuario() {
  const b = $("#boton-usuario");
  b.textContent = estado.perfil ? `Hola, ${estado.perfil.alias}` : "Crear mi perfil";
  const f = $("#formulario-perfil"), p = estado.perfil;
  if (!p) return;
  f.alias.value = p.alias || "";
  $$("input[name=tipo_piel]", f).forEach((r) => { r.checked = r.value === p.tipo_piel; });
  f.sensible.checked = !!p.sensible; f.embarazo.checked = !!p.embarazo;
  f.tipo_pelo.value = p.tipo_pelo || ""; f.evitar.value = (p.evitar || []).join(", ");
  f.presupuesto.value = p.presupuesto ?? ""; f.max_pasos.value = p.max_pasos ?? "";
  f.kbeauty.checked = p.preferencia_origen !== "indiferente";
  objetivosPerfil = (p.objetivos || []).filter((o) => o in OBJETIVOS.cara);
  pintarChipsPerfil();
}

function necesitaUsuario() {
  if (estado.usuarioId) return false;
  $("#dialogo-bienvenida").showModal();
  return true;
}

$("#boton-usuario").addEventListener("click", () => (estado.usuarioId ? irA("perfil") : $("#dialogo-bienvenida").showModal()));

$("#formulario-bienvenida").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const d = await api("/api/usuarios", { method: "POST", body: {
    alias: f.alias.value, perfil: { tipo_piel: f.querySelector("input[name=tipo_piel]:checked")?.value || "", sensible: f.sensible.checked } } });
  estado.usuarioId = d.id; guardar("dearskin-usuario", d.id);
  $("#dialogo-bienvenida").close();
  await refrescarUsuario();
});

$("#formulario-perfil").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, st = $("#estado-perfil");
  const perfil = {
    alias: f.alias.value, tipo_piel: f.querySelector("input[name=tipo_piel]:checked")?.value || "",
    sensible: f.sensible.checked, embarazo: f.embarazo.checked, tipo_pelo: f.tipo_pelo.value,
    evitar: f.evitar.value.split(",").map((x) => x.trim()).filter(Boolean),
    presupuesto: f.presupuesto.value ? Number(f.presupuesto.value) : null,
    max_pasos: f.max_pasos.value ? Number(f.max_pasos.value) : null,
    preferencia_origen: f.kbeauty.checked ? "kbeauty" : "indiferente",
    objetivos: [...objetivosPerfil, ...(estado.perfil?.objetivos || []).filter((o) => !(o in OBJETIVOS.cara))],
    deseos: $$("input[name=deseos]:checked", f).map((c) => c.value),
  };
  try {
    if (estado.usuarioId) await api(`/api/usuarios/${estado.usuarioId}/perfil`, { method: "PUT", body: perfil });
    else { const d = await api("/api/usuarios", { method: "POST", body: { alias: perfil.alias, perfil } }); estado.usuarioId = d.id; guardar("dearskin-usuario", d.id); }
    st.className = "estado-formulario"; st.textContent = "Perfil guardado. Dear Skin lo usará en tus próximas rutinas.";
    await refrescarUsuario();
  } catch (error) { st.className = "estado-formulario mal"; st.textContent = error.message; }
});

// ---------- Armario ----------

function pintarArmario() {
  const cont = $("#lista-armario");
  if (!estado.armario.length) { cont.innerHTML = `<p class="vacio">Tu armario está vacío. Busca lo que tienes en casa y añádelo.</p>`; return; }
  const porZona = {};
  estado.armario.forEach((a) => (porZona[a.zona] ||= []).push(a));
  cont.innerHTML = Object.entries(porZona).map(([zona, items]) => `<div class="grupo-armario"><h3>${ZONAS[zona] || zona}</h3><ul class="estante">
    ${items.map((a) => {
      const p = estado.productos[a.producto_id] || { id: `armario-${a.id}`, nombre: a.nombre, paso: a.paso };
      return `<li>${foto(p)}<p>${escapar(a.nombre)}</p><small>${escapar(a.zona === "cara" ? categoriaPaso({ ...a, ...p, subtipo: a.subtipo, objetivos: p.objetivos?.length ? p.objetivos : a.objetivos }).etiqueta : a.paso.replaceAll("_", " "))} · desde ${escapar(a.desde)}</small>
        <label class="solo-lectores" for="mom-${a.id}">Cuándo lo usas</label>
        <select class="momento-armario" id="mom-${a.id}" data-momento-item="${a.id}">
          ${[["ambos", "Mañana y noche"], ["manana", "Solo mañana"], ["noche", "Solo noche"]].map(([v, t]) =>
            `<option value="${v}" ${(a.momento || "ambos") === v ? "selected" : ""}>${t}</option>`).join("")}</select>
        <button class="enlace peligro" type="button" data-quitar="${a.id}">Quitar</button></li>`;
    }).join("")}</ul></div>`).join("");
}

async function anadirAlArmario(cuerpo) {
  if (necesitaUsuario()) return;
  const d = await api(`/api/usuarios/${estado.usuarioId}/armario`, { method: "POST", body: cuerpo });
  estado.armario = d.armario; pintarArmario(); pintarProductosDiario();
}

let temporizador;
$("#buscar-armario").addEventListener("input", (e) => {
  clearTimeout(temporizador);
  const q = e.target.value.trim();
  if (q.length < 3) { $("#resultados-armario").innerHTML = ""; return; }
  temporizador = setTimeout(async () => {
    const lista = await api(`/api/productos?q=${encodeURIComponent(q)}&limite=6`);
    lista.forEach((p) => { estado.productos[p.id] = p; });
    $("#resultados-armario").innerHTML = lista.length ? lista.map((p) => `<li>${foto(p, "mini")}<span>${escapar(p.marca)} · ${escapar(p.nombre)}
      <small>${escapar(p.paso.replace("_", " "))} · ${ZONAS[p.zona]}${p.precio ? ` · ${euros(p.precio)}` : ""}</small></span>
      <button class="boton-secundario" type="button" data-armario="${p.id}">Añadir</button></li>`).join("")
      : `<li class="vacio">No lo encuentro en el catálogo: añádelo a mano.</li>`;
  }, 250);
});

$("#formulario-propio").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  await anadirAlArmario({ nombre: f.nombre.value, paso: f.paso.value, zona: f.zona.value });
  f.reset();
});

document.addEventListener("change", async (e) => {
  if (e.target.dataset.momentoItem && estado.usuarioId) {
    const d = await api(`/api/usuarios/${estado.usuarioId}/armario/${e.target.dataset.momentoItem}`, { method: "PUT", body: { momento: e.target.value } });
    estado.armario = d.armario;
  }
});

// ---------- Skin journey ----------

function pintarProductosDiario() {
  const opciones = new Map();
  estado.armario.forEach((a) => opciones.set(a.producto_id || `armario-${a.id}`, a.nombre));
  if (estado.rutina) Object.values(estado.rutina.zonas).forEach((z) => Object.values(z).forEach((pasos) => pasos.forEach((p) => {
    if (!p.producto.id.startsWith("propio-")) opciones.set(p.producto.id, `${p.producto.marca} ${p.producto.nombre}`.trim());
  })));
  $("#productos-diario").innerHTML = opciones.size
    ? [...opciones].map(([id, nombre]) => `<label class="casilla"><input type="checkbox" name="productos" value="${escapar(id)}"> ${escapar(nombre)}</label>`).join("")
    : `<p class="vacio">Añade productos a tu armario o genera una rutina.</p>`;
  opciones.forEach((nombre, id) => { estado.nombres[id] = nombre; });
}

function pintarJourney(j, entradas = []) {
  const nombre = (id) => estado.nombres[id] || id;
  if (!j || !j.registros) {
    $("#resumen-journey").innerHTML = `<p class="vacio">Aún no hay registros. Cada semana, anota cómo te sientan tus productos.</p>`;
    return;
  }
  const lista = (ids) => ids.length ? `<ul>${ids.map((i) => `<li>${escapar(nombre(i))}</li>`).join("")}</ul>` : "<p>—</p>";
  $("#resumen-journey").innerHTML = `
    <h3>Lo que Dear Skin recuerda de tu piel</h3>
    <div class="recuerda">
      <section class="bloque"><h3>Toleras bien</h3>${lista(j.bien_tolerados)}</section>
      ${j.reaccionados.length ? `<section class="bloque alerta"><h3>Te sentaron mal</h3>${lista(j.reaccionados)}<p class="ayuda">No volveré a recomendártelos y vigilaré los ingredientes que comparten.</p></section>` : ""}
      ${j.sintomas_frecuentes.length ? `<section class="bloque"><h3>Lo que más anotas</h3><p>${j.sintomas_frecuentes.map(escapar).join(", ")}</p></section>` : ""}
    </div>
    <ol class="linea-tiempo">${entradas.map((e) => `<li class="${e.reaccion ? "reaccion" : ""}">
      <p class="fecha">${escapar(e.fecha)} <span class="puntos" aria-label="Tolerancia ${e.tolerancia} de 5">${"●".repeat(e.tolerancia)}${"○".repeat(5 - e.tolerancia)}</span></p>
      <p>${e.productos.map((p) => escapar(nombre(p))).join(", ")}</p>
      ${e.sintomas.length ? `<p>${e.sintomas.map(escapar).join(", ")}</p>` : ""}
      ${e.notas ? `<p><em>${escapar(e.notas)}</em></p>` : ""}</li>`).join("")}</ol>`;
}

$("#formulario-diario").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (necesitaUsuario()) return;
  const f = e.target, st = $("#estado-diario");
  const cuerpo = {
    productos: $$("input[name=productos]:checked", f).map((c) => c.value),
    tolerancia: Number(f.querySelector("input[name=tolerancia]:checked")?.value),
    sintomas: $$("input[name=sintomas]:checked", f).map((c) => c.value),
    reaccion: f.reaccion.checked, notas: f.notas.value, compartir_resena: f.compartir_resena.checked,
  };
  if (!cuerpo.productos.length) { st.className = "estado-formulario mal"; st.textContent = "Marca al menos un producto."; return; }
  try {
    const d = await api(`/api/usuarios/${estado.usuarioId}/diario`, { method: "POST", body: cuerpo });
    pintarJourney(d.journey, d.diario);
    st.className = "estado-formulario"; st.textContent = "Guardado. Lo tendré en cuenta en tus próximas recomendaciones.";
    f.reset(); pintarProductosDiario();
  } catch (error) { st.className = "estado-formulario mal"; st.textContent = error.message; }
});

// ---------- ¿Merece la pena? ----------

function pintarHype(r) {
  const cont = $("#resultado-hype");
  if (!r.encontrado) {
    cont.innerHTML = `<p>No encuentro «${escapar(r.consulta)}» en el catálogo.${r.sugerencias.length ? ` ¿Quizá: ${r.sugerencias.map(escapar).join(", ")}?` : ""}</p>
      <p class="ayuda">${escapar(r.nota)} También puedes preguntarlo en el chat.</p>`;
    return;
  }
  const bloque = (titulo, items, clase = "") => items.length ? `<section class="bloque ${clase}"><h3>${titulo}</h3><ul>${items.join("")}</ul></section>` : "";
  cont.innerHTML = `<div class="veredicto">
    <div>
      <p class="veredicto-titular ${r.veredicto}">${VEREDICTOS[r.veredicto]}</p>
      <p>${escapar(r.veredicto_texto)}</p>
      ${bloque("Por qué no", r.problemas.map((p) => `<li>${escapar(p)}</li>`), "alerta")}
      ${bloque("Ya tienes algo parecido", r.equivalentes.map((e) => `<li>${escapar(e.producto)}: ${escapar(e.razon)}</li>`))}
      ${bloque("Lo que aportaría a tu rutina", r.aporta.map((a) => `<li>${escapar(a)}</li>`))}
      ${bloque("Ojo con", [...r.advertencias.map((a) => `<li>${escapar(a)}</li>`),
        ...r.conflictos.map((c) => `<li>Con ${escapar(c.con)}: ${escapar(c.consejo)}</li>`)])}
      ${Object.keys(r.evidencia).length ? `<section class="bloque"><h3>¿Hay ciencia detrás?</h3><dl class="evidencia">${Object.entries(r.evidencia).map(([i, e]) =>
        `<dt>${escapar(i)}</dt><dd class="${e}">${{ strong: "Mucha", moderate: "Moderada", limited: "Poca" }[e] || e}</dd>`).join("")}</dl>
        ${r.poca_evidencia ? `<p class="ayuda">Sus ingredientes estrella tienen poca evidencia: el hype va por delante de los estudios.</p>` : ""}</section>` : ""}
      ${bloque("Alternativas más baratas", r.alternativas_baratas.map((a) => `<li>${escapar(a.producto)} · ${euros(a.precio)} (comparte ${a.comparten.map(escapar).join(", ")})</li>`))}
    </div>
    <div class="productos">${tarjetaProducto({ ...r.producto, resenas: { total: 0 } })}</div>
  </div>`;
}

$("#formulario-hype").addEventListener("submit", async (e) => {
  e.preventDefault();
  const producto = $("#entrada-hype").value.trim();
  if (!producto) return;
  $("#resultado-hype").innerHTML = `<p class="vacio">Analizando…</p>`;
  try { pintarHype(await api("/api/hype", { method: "POST", body: { producto, usuario_id: estado.usuarioId } })); }
  catch (error) { $("#resultado-hype").innerHTML = `<p class="estado-formulario mal">${escapar(error.message)}</p>`; }
});

// ---------- ¿Se pueden juntar? ----------

const VEREDICTO = { no: ["No los juntes", "no"], separar: ["Mejor por separado", "separar"],
                    si: ["Se pueden juntar", "si"], sin_regla: ["Sin regla conocida", "sin-regla"] };
estado.juntar = [];
function pintarElegidosJuntar() {
  $("#elegidos-juntar").innerHTML = estado.juntar.map(({ t }, i) =>
    `<span class="chip-juntar">${escapar(t)}<button type="button" data-quitar-juntar="${i}" aria-label="Quitar ${escapar(t)}">×</button></span>`).join("");
  $("#boton-juntar").disabled = estado.juntar.length < 2;
}
function anadirJuntar(texto, valor = texto) {
  texto = texto.trim();
  if (!texto || estado.juntar.length >= 6 || estado.juntar.some(({ t }) => t.toLowerCase() === texto.toLowerCase())) return;
  estado.juntar.push({ t: texto, v: valor }); pintarElegidosJuntar();
}
$("#formulario-juntar").addEventListener("submit", (e) => {
  e.preventDefault(); anadirJuntar($("#entrada-juntar").value); $("#entrada-juntar").value = "";
});
$("#elegidos-juntar").addEventListener("click", (e) => {
  const i = e.target.dataset.quitarJuntar;
  if (i !== undefined) { estado.juntar.splice(Number(i), 1); pintarElegidosJuntar(); }
});
$("#juntar-armario").addEventListener("click", () => {
  const activos = estado.armario.filter((a) => a.zona === "cara" && ["serum", "tratamiento", "tonico", "esencia", "contorno"].includes(a.paso));
  if (!activos.length) { $("#resultado-juntar").innerHTML = `<p class="vacio">Tu armario no tiene sérums ni tratamientos todavía.</p>`; return; }
  estado.juntar = []; activos.slice(0, 6).forEach((a) => anadirJuntar(a.nombre, a.producto_id || a.nombre));
});
document.addEventListener("click", (e) => {
  const ej = e.target.dataset?.juntarEjemplo;
  if (ej) { estado.juntar = []; ej.split("|").forEach(anadirJuntar); }
});
$("#boton-juntar").addEventListener("click", async (e) => {
  e.target.disabled = true; e.target.textContent = "Comprobando…";
  try {
    const r = await api("/api/compatibilidad", { method: "POST", body: { elementos: estado.juntar.map(({ v }) => v), usuario_id: estado.usuarioId } });
    $("#resultado-juntar").innerHTML = `<div class="informe">
      <section><h3 class="titulo-seccion">Cada uno</h3><div class="fichas-juntar">${r.elementos.map((x) => `
        <article class="ficha-juntar"><h4>${escapar(x.nombre)}</h4><p class="momento-juntar">${escapar(x.momento)}</p>
          ${x.familias.map((f) => `<p><b>${escapar(f.familia)}</b>. ${escapar(f.nota)}</p>`).join("") || "<p>Sin activos con función destacados.</p>"}
          ${x.avisos_piel.map((a) => `<p class="aviso-piel">${escapar(a)}</p>`).join("")}</article>`).join("")}</div></section>
      <section><h3 class="titulo-seccion">Juntos</h3><ul class="pares-juntar">${r.pares.map((p) => `
        <li class="par ${VEREDICTO[p.veredicto][1]}"><h4>${escapar(p.a)} + ${escapar(p.b)}<span class="veredicto">${VEREDICTO[p.veredicto][0]}</span></h4>
          ${p.relaciones.map((x) => `<p><b>${escapar(x.titulo)}.</b> ${escapar(x.porque)} <em>${escapar(x.como)}</em></p>`).join("")
            || "<p>No tengo ninguna regla para esta pareja. No es una garantía: introdúcelos de uno en uno.</p>"}</li>`).join("")}</ul></section>
      ${r.no_encontrados.length ? `<p class="ayuda">No reconozco: ${r.no_encontrados.map(escapar).join(", ")}. Prueba con el nombre del ingrediente.</p>` : ""}
      <p class="ayuda">${escapar(r.aviso)}</p></div>`;
  } catch (error) { $("#resultado-juntar").innerHTML = `<p class="estado-formulario mal">${escapar(error.message)}</p>`; }
  finally { e.target.textContent = "Comprobar"; e.target.disabled = estado.juntar.length < 2; }
});

// ---------- Reseñas ----------

async function verResenas(id) {
  $("#titulo-resenas").textContent = estado.nombres[id] || "Reseñas";
  $("#contenido-resenas").innerHTML = "<p>Cargando…</p>";
  $("#dialogo-resenas").showModal();
  const tipo = estado.perfil?.tipo_piel || "";
  const { resumen, resenas } = await api(`/api/productos/${id}/resenas?tipo_piel=${encodeURIComponent(tipo)}`);
  if (!resumen.total) {
    $("#contenido-resenas").innerHTML = `<p>Nadie ha reseñado este producto todavía.</p>
      <button class="boton-principal" type="button" data-resenar="${id}">Escribir la primera reseña</button>`;
    return;
  }
  const largo = resumen.largo_plazo.media ? `★ ${resumen.largo_plazo.media} (${resumen.largo_plazo.total})` : "Sin datos";
  const tuyo = resumen.tu_tipo_de_piel?.total ? `<div><dt>Piel ${escapar(tipo)}</dt><dd>★ ${resumen.tu_tipo_de_piel.media}</dd></div>` : "";
  $("#contenido-resenas").innerHTML = `
    <dl class="cifras">
      <div><dt>Media</dt><dd>★ ${resumen.media}</dd></div>
      <div><dt>Tras 8+ semanas</dt><dd>${largo}</dd></div>
      <div class="${resumen.porcentaje_reacciones ? "alerta" : ""}"><dt>Con reacción</dt><dd>${resumen.porcentaje_reacciones} %</dd></div>
      ${tuyo}
    </dl>
    <ul class="lista-resenas">${resenas.map((r) => `<li>
      <p class="meta">${"★".repeat(r.puntuacion)}${"☆".repeat(5 - r.puntuacion)} · piel ${escapar(r.tipo_piel)} · ${r.semanas_uso} semanas · ${escapar(r.alias)}
        ${r.es_ejemplo ? '<span class="insignia">ejemplo</span>' : ""}${r.reaccion ? '<span class="insignia reaccion">reacción</span>' : ""}</p>
      <p>${escapar(r.texto.replace(/^\[Reseña de ejemplo\]\s*/, ""))}</p></li>`).join("")}</ul>
    <p><button class="boton-secundario" type="button" data-resenar="${id}">Escribir una reseña</button></p>`;
}

function abrirNuevaResena(id) {
  $("#dialogo-resenas").close();
  $("#estado-resena").textContent = "";
  $("#id-producto-resena").value = id;
  $("#nombre-producto-resena").value = estado.nombres[id] || id;
  $("#dialogo-nueva").showModal();
}

$("#formulario-resena").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, st = $("#estado-resena");
  const datos = Object.fromEntries(new FormData(f));
  try {
    await api("/api/resenas", { method: "POST", body: {
      producto_id: datos.producto_id, alias: datos.alias || estado.perfil?.alias || "anónimo", tipo_piel: datos.tipo_piel,
      puntuacion: Number(datos.puntuacion), semanas_uso: Number(datos.semanas_uso), reaccion: f.reaccion.checked, texto: datos.texto } });
    st.className = "estado-formulario"; st.textContent = "Reseña publicada. Ayudará a otras personas con tu tipo de piel.";
    f.reset();
  } catch { st.className = "estado-formulario mal"; st.textContent = "No se ha publicado: elige una puntuación y las semanas de uso."; }
});

// ---------- Clics globales ----------

document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.ver) verResenas(b.dataset.ver);
  if (b.dataset.resenar) abrirNuevaResena(b.dataset.resenar);
  if (b.dataset.ir) irA(b.dataset.ir);
  if (b.dataset.armario) { await anadirAlArmario({ producto_id: b.dataset.armario }); if (estado.usuarioId) b.textContent = "En tu armario"; }
  if (b.dataset.quitar) {
    const d = await api(`/api/usuarios/${estado.usuarioId}/armario/${b.dataset.quitar}`, { method: "DELETE" });
    estado.armario = d.armario; pintarArmario(); pintarProductosDiario();
  }
  if (b.dataset.cambiar) enviar(`No me convence ${b.dataset.cambiar} en mi rutina. ¿Me lo cambias por otra opción?`);
  if (b.dataset.opcion) elegirOpcion(b.dataset.opcion, b.dataset.roles.split(","), b);
  if (b.dataset.anadir) {
    const [momento, ...resto] = b.dataset.anadir.split(":");
    anadirAlConstructor(momento, resto.join(":"));
    $(`#buscar-${momento}`).value = ""; b.closest("ul").innerHTML = "";
  }
  if (b.dataset.dia) {
    const [momento, i, j, d] = b.dataset.dia.split(":");
    const it = estado.rutinaActual[momento][i].items[j];
    it.dias = it.dias.includes(d) ? it.dias.filter((x) => x !== d) : [...it.dias, d];
    pintarConstructor();
  }
  if (b.dataset.quitarItem) {
    const [momento, i, j] = b.dataset.quitarItem.split(":").map((x, k) => (k ? Number(x) : x));
    const paso = estado.rutinaActual[momento][i];
    paso.items.splice(j, 1);
    if (!paso.items.length) estado.rutinaActual[momento].splice(i, 1);
    else paso.items[0].dias = [...DIAS];
    pintarConstructor();
  }
  if (b.dataset.mover) {
    const [momento, i, delta] = b.dataset.mover.split(":").map((x, k) => (k ? Number(x) : x));
    const lista = estado.rutinaActual[momento], k = i + delta;
    if (k >= 0 && k < lista.length) { [lista[i], lista[k]] = [lista[k], lista[i]]; pintarConstructor(); }
  }
  if (b.dataset.alternar) {
    const [momento, i] = b.dataset.alternar.split(":");
    destinoAlternar = { momento, i: Number(i) };
    const entrada = $(`#buscar-${momento}`);
    entrada.placeholder = "Busca el producto que alternas…"; entrada.focus();
  }
  if (b.id === "usar-semana" && estado.ultimaRevision) {
    estado.rutinaActual = semanaARutina(estado.ultimaRevision.semana_propuesta);
    pintarConstructor();
    $("#panel-revisar").scrollIntoView({ behavior: "smooth" });
  }
  if (b.dataset.elegir) enviar(`Me quedo con ${b.dataset.elegir}: ponlo en mi rutina.`);
  if (b.hasAttribute("data-cerrar")) b.closest("dialog").close();
});

// ---------- Inicio ----------

async function iniciar() {
  pintarChipsObjetivos();
  pintarChipsPerfil();
  try {
    const productos = await api("/api/productos?limite=500");
    productos.forEach((p) => { estado.nombres[p.id] = `${p.marca} ${p.nombre}`; estado.productos[p.id] = p; });
    $("#lista-productos").innerHTML = productos.map((p) => `<option value="${escapar(p.marca + " " + p.nombre)}">`).join("");
  } catch { /* el catálogo se cargará cuando el servidor responda */ }
  try { const guardada = JSON.parse(localStorage.getItem("dearskin-rutina-actual") || "null"); if (guardada) estado.rutinaActual = guardada; } catch { /* nada */ }
  pintarConstructor();
  await refrescarUsuario();
  pintarArmario();
  if (!estado.usuarioId) pintarJourney(null);
}
iniciar();
