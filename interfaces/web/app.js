"use strict";
// App del asistente para el celular. Sin dependencias externas (la CSP solo permite este origen).

const $ = (sel) => document.querySelector(sel);
const CLAVE_TOKEN = "asistente.token";
const CLAVE_CHAT = "asistente.chat";
const CLAVE_LEER = "asistente.leer";

const guardar = (clave, valor) => { try { localStorage.setItem(clave, valor); } catch (_) {} };
const leer = (clave) => { try { return localStorage.getItem(clave); } catch (_) { return null; } };
const borrar = (clave) => { try { localStorage.removeItem(clave); } catch (_) {} };

let token = leer(CLAVE_TOKEN) || "";
let vista = "chat";
let ocupado = false;
let detenido = false;

// ---------- utilidades ----------
function el(tag, props = {}, ...hijos) {
  const nodo = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") nodo.className = v;
    else if (k.startsWith("on")) nodo.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) nodo.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat()) if (h !== null && h !== undefined && h !== false) nodo.append(h instanceof Node ? h : String(h));
  return nodo;
}

let temporizadorAviso;
function aviso(texto, error = false) {
  const t = $("#aviso");
  t.textContent = texto;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => (t.hidden = true), 4500);
}

function fecha(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const hoy = new Date();
  const hora = d.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === hoy.toDateString() ? hora : d.toLocaleDateString("es-CO", { day: "numeric", month: "short" }) + " " + hora;
}

async function api(ruta, opciones = {}) {
  const resp = await fetch(ruta, {
    ...opciones,
    headers: { Authorization: "Bearer " + token, ...(opciones.body && typeof opciones.body === "string" ? { "Content-Type": "application/json" } : {}), ...(opciones.headers || {}) },
  });
  if (resp.status === 401) { salir("El token ya no es válido."); throw new Error("Token incorrecto."); }
  if (!resp.ok) {
    let detalle = resp.statusText;
    try { detalle = (await resp.json()).detail || detalle; } catch (_) {}
    throw new Error(typeof detalle === "string" ? detalle : JSON.stringify(detalle));
  }
  return resp;
}
const apiJson = async (ruta, opciones) => (await api(ruta, opciones)).json();
const post = (ruta, cuerpo) => apiJson(ruta, { method: "POST", body: JSON.stringify(cuerpo || {}) });

// ---------- entrada ----------
async function entrar(nuevo) {
  token = nuevo.trim();
  const resp = await fetch("/api/login", { method: "POST", headers: { Authorization: "Bearer " + token } });
  if (!resp.ok) {
    token = "";
    let detalle = "Token incorrecto.";
    try { detalle = (await resp.json()).detail || detalle; } catch (_) {}
    throw new Error(detalle);
  }
  guardar(CLAVE_TOKEN, token);
  mostrarApp();
}

function salir(motivo) {
  token = "";
  borrar(CLAVE_TOKEN);
  $("#app").hidden = true;
  $("#login").hidden = false;
  $("#login-error").textContent = motivo || "";
}

function mostrarApp() {
  $("#login").hidden = true;
  $("#app").hidden = false;
  pintarHistorial();
  refrescarEstado();
  refrescarContadores();
}

// ---------- estado y parada ----------
const NOMBRES_ESTADO = { idle: "listo", thinking: "pensando…", searching: "buscando…", working: "trabajando…", speaking: "hablando…", listening: "escuchando…", happy: "listo", error: "hubo un error", sleeping: "en reposo" };

async function refrescarEstado() {
  if (!token || document.hidden) return;
  try {
    const e = await apiJson("/api/estado");
    detenido = e.detenido;
    const punto = $("#estado-punto");
    punto.className = "dot " + (e.detenido ? "stopped" : e.estado);
    const motor = e.motor ? ` · ${e.motor}` : "";
    $("#estado-texto").textContent = e.detenido ? "detenido (parada de emergencia)" : (NOMBRES_ESTADO[e.estado] || e.estado) + motor + (e.ollama ? "" : " · Ollama apagado");
    const boton = $("#btn-parar");
    boton.textContent = e.detenido ? "REANUDAR" : "PARAR";
    boton.classList.toggle("resume", e.detenido);
  } catch (err) {
    $("#estado-punto").className = "dot error";
    $("#estado-texto").textContent = "sin conexión con el PC";
  }
}

async function alternarParada() {
  try {
    const r = await post(detenido ? "/api/reanudar" : "/api/parar");
    aviso(r.mensaje);
  } catch (err) { aviso(err.message, true); }
  refrescarEstado();
}

// ---------- chat ----------
let historial = [];
try { historial = JSON.parse(leer(CLAVE_CHAT) || "[]"); } catch (_) { historial = []; }

function guardarHistorial() { guardar(CLAVE_CHAT, JSON.stringify(historial.slice(-60))); }

function burbuja(m) {
  const nodo = el("div", { class: "msg " + (m.de === "yo" ? "yo" : "bot") + (m.error ? " error" : "") });
  pintarTexto(nodo, m.texto);
  if (m.motor) nodo.append(el("span", { class: "motor" }, m.motor));
  return nodo;
}

// Texto con bloques ``` como <pre>, sin interpretar HTML.
function pintarTexto(nodo, texto) {
  nodo.replaceChildren();
  const partes = String(texto).split("```");
  partes.forEach((parte, i) => {
    if (i % 2) nodo.append(el("pre", {}, parte.replace(/^[\w-]*\n/, "")));
    else if (parte) nodo.append(parte);
  });
}

function pintarHistorial() {
  const caja = $("#mensajes");
  caja.replaceChildren();
  if (!historial.length) {
    caja.append(el("div", { class: "empty-chat" }, el("p", {}, "Hola. Escríbeme o pulsa el micrófono para mandarme una nota de voz."), el("p", {}, "Desde aquí no ejecuto PowerShell ni instalo habilidades: eso lo apruebas en el PC.")));
    return;
  }
  historial.forEach((m) => caja.append(burbuja(m)));
  caja.scrollTop = caja.scrollHeight;
}

async function enviar(texto) {
  texto = texto.trim();
  if (!texto || ocupado) return;
  ocupado = true;
  $("#btn-enviar").disabled = true;
  if (!historial.length) $("#mensajes").replaceChildren();
  historial.push({ de: "yo", texto });
  guardarHistorial();
  const caja = $("#mensajes");
  caja.append(burbuja({ de: "yo", texto }));
  const respuesta = el("div", { class: "msg bot pensando" }, "Pensando…");
  caja.append(respuesta);
  caja.scrollTop = caja.scrollHeight;
  let acumulado = "";
  let final = null;
  try {
    const resp = await api("/api/chat", { method: "POST", body: JSON.stringify({ texto }) });
    const lector = resp.body.getReader();
    const decodificador = new TextDecoder();
    let resto = "";
    for (;;) {
      const { value, done } = await lector.read();
      if (done) break;
      resto += decodificador.decode(value, { stream: true });
      const lineas = resto.split("\n");
      resto = lineas.pop();
      for (const linea of lineas) {
        if (!linea.trim()) continue;
        const dato = JSON.parse(linea);
        if (dato.t) {
          acumulado += dato.t;
          respuesta.classList.remove("pensando");
          pintarTexto(respuesta, acumulado);
        } else if (dato.fin !== undefined) {
          final = { de: "bot", texto: dato.fin, motor: dato.motor };
        } else if (dato.error) {
          final = { de: "bot", texto: "Error: " + dato.error, error: true };
        }
      }
      caja.scrollTop = caja.scrollHeight;
    }
  } catch (err) {
    final = { de: "bot", texto: "No pude hablar con el PC: " + err.message, error: true };
  }
  final = final || { de: "bot", texto: acumulado || "(sin respuesta)" };
  respuesta.replaceWith(burbuja(final));
  historial.push(final);
  guardarHistorial();
  caja.scrollTop = caja.scrollHeight;
  if (!final.error && $("#leer-respuestas").checked) hablar(final.texto);
  ocupado = false;
  $("#btn-enviar").disabled = false;
  refrescarContadores();
}

function hablar(texto) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const frase = new SpeechSynthesisUtterance(texto.replace(/```[\s\S]*?```/g, " (código) ").slice(0, 1500));
  frase.lang = "es-CO";
  const voz = speechSynthesis.getVoices().find((v) => v.lang.startsWith("es"));
  if (voz) frase.voice = voz;
  speechSynthesis.speak(frase);
}

// Nota de voz: pulsa para grabar, pulsa otra vez para enviar.
let grabadora = null;
let trozos = [];
async function alternarGrabacion() {
  const boton = $("#btn-mic");
  if (grabadora && grabadora.state === "recording") { grabadora.stop(); return; }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    aviso("Este navegador no permite grabar aquí. Abre la app por HTTPS (tailscale serve).", true);
    return;
  }
  try {
    const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
    trozos = [];
    grabadora = new MediaRecorder(flujo);
    grabadora.ondataavailable = (e) => e.data.size && trozos.push(e.data);
    grabadora.onstop = async () => {
      flujo.getTracks().forEach((p) => p.stop());
      boton.classList.remove("recording");
      const tipo = grabadora.mimeType || "audio/webm";
      const audio = new Blob(trozos, { type: tipo });
      if (audio.size < 1500) { aviso("La grabación quedó vacía."); return; }
      aviso("Transcribiendo…");
      try {
        const r = await apiJson("/api/voz", { method: "POST", body: audio, headers: { "Content-Type": tipo } });
        if (r.texto) enviar(r.texto); else aviso("No entendí el audio. ¿Lo repites?", true);
      } catch (err) { aviso(err.message, true); }
    };
    grabadora.start();
    boton.classList.add("recording");
    aviso("Grabando… pulsa otra vez para enviar.");
  } catch (err) {
    aviso("Sin permiso para el micrófono: " + err.message, true);
  }
}

// ---------- tareas ----------
const ACCIONES_TAREA = {
  pendiente: [["pausar", "Pausar"], ["cancelar", "Cancelar"]],
  ejecutando: [["cancelar", "Cancelar"]],
  pausada: [["reactivar", "Reactivar"], ["cancelar", "Cancelar"]],
  fallida: [["reactivar", "Reintentar"]],
};

function chipEstado(estado) {
  return el("span", { class: "chip " + estado }, estado.replace("_", " "));
}

async function cargarTareas() {
  const lista = $("#lista-tareas");
  try {
    const datos = await apiJson("/api/tareas?todas=" + $("#tareas-todas").checked);
    lista.replaceChildren();
    if (!datos.length) { lista.append(el("p", { class: "empty" }, "No hay tareas. Pon una en cola arriba.")); return; }
    for (const t of datos) {
      const acciones = (t.tipo === "programa" ? [] : ACCIONES_TAREA[t.estado] || []).map(([accion, texto]) =>
        el("button", { class: "btn btn-sm" + (accion === "cancelar" ? " btn-danger" : ""), type: "button", onclick: () => accionTarea(t.id, accion) }, texto));
      if (t.tipo === "programa") acciones.push(el("button", { class: "btn btn-sm", type: "button", onclick: () => { cambiarVista("cambios"); abrirCambio(t.id); } }, "Ver cambio"));
      const pie = t.proximo_paso || t.resultado || t.error || "";
      lista.append(el("article", { class: "item" },
        el("div", { class: "item-top" }, el("span", { class: "item-meta" }, `[${t.id}] ${t.tipo} · ${fecha(t.programada_para || t.creada)}`), chipEstado(t.estado)),
        el("div", { class: "item-title" }, t.objetivo),
        pie ? el("div", { class: "item-meta" }, pie.slice(0, 280)) : null,
        acciones.length ? el("div", { class: "item-actions" }, acciones) : null));
    }
  } catch (err) { lista.replaceChildren(el("p", { class: "empty" }, err.message)); }
}

async function accionTarea(id, accion) {
  if (accion === "cancelar" && !confirm("¿Cancelar la tarea " + id + "?")) return;
  try { await post(`/api/tareas/${id}/${accion}`); aviso("Hecho."); } catch (err) { aviso(err.message, true); }
  cargarTareas();
  refrescarContadores();
}

// ---------- cambios de código ----------
async function cargarCambios() {
  const lista = $("#lista-cambios");
  $("#detalle-cambio").hidden = true;
  lista.hidden = false;
  try {
    const datos = await apiJson("/api/cambios?todos=" + $("#cambios-todos").checked);
    lista.replaceChildren();
    if (!datos.length) { lista.append(el("p", { class: "empty" }, "No hay cambios pendientes. Pídelos en el chat: «prográmate un comando /hora»." )); return; }
    for (const t of datos) {
      const listo = t.estado === "esperando_autorizacion" && t.datos.commit;
      const estadoTexto = t.estado === "esperando_autorizacion" ? (t.datos.commit ? "listo para revisar" : "esperando que lo apruebes para empezar") : t.estado;
      lista.append(el("article", { class: "item clickable", onclick: () => abrirCambio(t.id) },
        el("div", { class: "item-top" }, el("span", { class: "item-meta" }, `[${t.id}] ${fecha(t.actualizada)}`), chipEstado(t.estado)),
        el("div", { class: "item-title" }, t.objetivo),
        el("div", { class: "item-meta" }, estadoTexto + (listo ? (t.datos.pruebas_ok ? " · pruebas OK" : " · ⚠ pruebas fallan") : ""))));
    }
  } catch (err) { lista.replaceChildren(el("p", { class: "empty" }, err.message)); }
}

function pintarDiff(texto) {
  const caja = el("div", { class: "diff" });
  for (const linea of texto.split("\n")) {
    let clase = "";
    if (linea.startsWith("diff --git")) clase = "file";
    else if (linea.startsWith("@@")) clase = "hunk";
    else if (linea.startsWith("+") && !linea.startsWith("+++")) clase = "add";
    else if (linea.startsWith("-") && !linea.startsWith("---")) clase = "del";
    caja.append(el("div", { class: clase }, linea || " "));
  }
  return caja;
}

async function abrirCambio(id) {
  const detalle = $("#detalle-cambio");
  $("#lista-cambios").hidden = true;
  detalle.hidden = false;
  detalle.replaceChildren(el("p", { class: "empty" }, "Cargando…"));
  try {
    const c = await apiJson("/api/cambios/" + id);
    const t = c.tarea;
    const botones = [el("button", { class: "btn", type: "button", onclick: cargarCambios }, "← Volver")];
    if (c.puede_empezar) botones.push(el("button", { class: "btn btn-primary", type: "button", onclick: () => accionCambio(id, "empezar", "¿Dejar que el agente empiece a programar este cambio?") }, "Aprobar inicio"));
    if (c.puede_aplicar) botones.push(el("button", { class: "btn btn-primary", type: "button", onclick: () => aplicarCambio(id, c) }, "Aplicar a mi código"));
    if (c.puede_aplicar || c.puede_empezar || t.estado === "fallida") botones.push(el("button", { class: "btn btn-danger", type: "button", onclick: () => accionCambio(id, "rechazar", "¿Descartar este cambio? Tu código no se toca.") }, "Rechazar"));
    if (c.puede_deshacer) botones.push(el("button", { class: "btn btn-danger", type: "button", onclick: () => accionCambio(id, "deshacer", "¿Deshacer este cambio ya aplicado?") }, "Deshacer"));
    const archivos = c.datos.archivos || [];
    detalle.replaceChildren(
      el("div", { class: "card stack" },
        el("div", { class: "item-top" }, el("span", { class: "item-meta" }, `[${t.id}]`), chipEstado(t.estado)),
        el("div", { class: "item-title" }, t.objetivo),
        archivos.length ? el("div", { class: "item-meta" }, "Archivos: " + archivos.join(", ")) : null,
        c.datos.commit ? el("div", { class: "item-meta" }, c.datos.pruebas_ok ? "✅ Las pruebas pasan con este cambio" : "⚠ Las pruebas FALLAN con este cambio") : null,
        t.resultado ? el("pre", { class: "resumen" }, t.resultado) : null),
      c.avisos.length ? el("div", { class: "alerta" }, el("strong", {}, `⚠ ${c.avisos.length} línea(s) tocan seguridad, comandos o secretos. Revísalas:`), el("pre", {}, c.avisos.slice(0, 30).join("\n"))) : null,
      c.diff ? pintarDiff(c.diff) : el("p", { class: "empty" }, c.datos.merge ? "Ya aplicado (commit " + c.datos.merge.slice(0, 7) + ")." : "Aún no hay código que revisar."),
      el("div", { class: "sticky-actions" }, botones));
  } catch (err) { detalle.replaceChildren(el("p", { class: "empty" }, err.message), el("button", { class: "btn", type: "button", onclick: cargarCambios }, "← Volver")); }
}

async function aplicarCambio(id, c) {
  const archivos = (c.datos.archivos || []).join(", ");
  if (!confirm(`¿Aplicar a tu código los cambios en ${archivos || "estos archivos"}?`)) return;
  let aceptar = false;
  if (!c.datos.pruebas_ok) {
    if (!confirm("⚠ Las pruebas FALLAN con este cambio. ¿Aplicarlo de todos modos?")) return;
    aceptar = true;
  }
  try {
    const r = await post(`/api/cambios/${id}/aplicar`, { aceptar_pruebas_fallidas: aceptar });
    aviso(r.mensaje);
  } catch (err) { aviso(err.message, true); }
  abrirCambio(id);
  refrescarContadores();
}

async function accionCambio(id, accion, pregunta) {
  if (!confirm(pregunta)) return;
  try { aviso((await post(`/api/cambios/${id}/${accion}`)).mensaje); } catch (err) { aviso(err.message, true); }
  abrirCambio(id);
  refrescarContadores();
}

// ---------- memoria ----------
async function cargarMemoria() {
  const lista = $("#lista-memoria");
  try {
    const datos = await apiJson("/api/memoria");
    lista.replaceChildren();
    if (!datos.length) { lista.append(el("p", { class: "empty" }, "Aún no sé nada de ti. Cuéntame en el chat: «me llamo…», «me gusta…»." )); return; }
    let grupo = "";
    for (const h of datos) {
      if (h.categoria !== grupo) { grupo = h.categoria; lista.append(el("div", { class: "grupo" }, grupo)); }
      lista.append(el("article", { class: "item" },
        el("div", { class: "item-top" },
          el("div", {}, el("div", { class: "item-title" }, h.valor), el("div", { class: "item-meta" }, h.clave + " · " + fecha(h.actualizado))),
          el("button", { class: "btn btn-sm btn-danger", type: "button", onclick: () => olvidar(h) }, "Olvidar"))));
    }
  } catch (err) { lista.replaceChildren(el("p", { class: "empty" }, err.message)); }
}

async function olvidar(h) {
  if (!confirm(`¿Olvidar «${h.valor}»?`)) return;
  try { await apiJson("/api/memoria/" + h.id, { method: "DELETE" }); aviso("Olvidado."); } catch (err) { aviso(err.message, true); }
  cargarMemoria();
}

// ---------- actividad ----------
async function cargarActividad() {
  const lista = $("#lista-actividad");
  try {
    const datos = await apiJson("/api/actividad?limite=80");
    lista.replaceChildren();
    if (!datos.length) { lista.append(el("p", { class: "empty" }, "Sin actividad registrada.")); return; }
    for (const a of datos) {
      lista.append(el("article", { class: "item" + (a.ok ? "" : " fail") },
        el("div", { class: "item-top" }, el("span", { class: "item-title" }, (a.ok ? "" : "✗ ") + a.nombre), el("span", { class: "chip" }, a.origen)),
        el("div", { class: "item-meta" }, `${fecha(a.fecha)} · ${a.tipo}${a.detalle ? " · " + a.detalle.slice(0, 120) : ""}`),
        a.resultado ? el("div", { class: "item-meta" }, a.resultado.slice(0, 160)) : null));
    }
  } catch (err) { lista.replaceChildren(el("p", { class: "empty" }, err.message)); }
}

// ---------- navegación ----------
const CARGAS = { tareas: cargarTareas, cambios: cargarCambios, memoria: cargarMemoria, actividad: cargarActividad };

function cambiarVista(nombre) {
  vista = nombre;
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.vista === nombre));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "vista-" + nombre));
  if (CARGAS[nombre]) CARGAS[nombre]();
}

async function refrescarContadores() {
  if (!token) return;
  try {
    const activas = await apiJson("/api/tareas");
    const porRevisar = activas.filter((t) => t.tipo === "programa" && t.estado === "esperando_autorizacion").length;
    const enCurso = activas.filter((t) => t.tipo !== "programa").length;
    const fijar = (id, n) => { const b = $(id); b.hidden = !n; b.textContent = n; };
    fijar("#badge-cambios", porRevisar);
    fijar("#badge-tareas", enCurso);
  } catch (_) {}
}

function crecer(area) {
  area.style.height = "auto";
  area.style.height = Math.min(area.scrollHeight, 140) + "px";
}

// ---------- arranque ----------
document.addEventListener("DOMContentLoaded", () => {
  // Enlace de acceso rápido: /#t=<token> (el fragmento no viaja al servidor).
  const fragmento = new URLSearchParams(location.hash.slice(1));
  if (fragmento.get("t")) {
    token = fragmento.get("t");
    history.replaceState(null, "", location.pathname);
  }

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#login-error").textContent = "";
    try { await entrar($("#login-token").value); } catch (err) { $("#login-error").textContent = err.message; }
  });
  $("#btn-parar").addEventListener("click", alternarParada);
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const area = $("#chat-texto");
    const texto = area.value;
    area.value = "";
    crecer(area);
    enviar(texto);
  });
  $("#chat-texto").addEventListener("input", (e) => crecer(e.target));
  $("#chat-texto").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && matchMedia("(pointer: fine)").matches) {
      e.preventDefault();
      $("#chat-form").requestSubmit();
    }
  });
  $("#btn-mic").addEventListener("click", alternarGrabacion);
  $("#leer-respuestas").checked = leer(CLAVE_LEER) === "1";
  $("#leer-respuestas").addEventListener("change", (e) => guardar(CLAVE_LEER, e.target.checked ? "1" : "0"));
  $("#btn-borrar-chat").addEventListener("click", () => { historial = []; guardarHistorial(); pintarHistorial(); });
  $("#tarea-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await post("/api/tareas", { objetivo: $("#tarea-objetivo").value });
      $("#tarea-objetivo").value = "";
      aviso(r.mensaje);
    } catch (err) { aviso(err.message, true); }
    cargarTareas();
    refrescarContadores();
  });
  $("#tareas-todas").addEventListener("change", cargarTareas);
  $("#cambios-todos").addEventListener("change", cargarCambios);
  $("#btn-actividad").addEventListener("click", cargarActividad);
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => cambiarVista(b.dataset.vista)));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refrescarEstado(); refrescarContadores(); } });
  setInterval(refrescarEstado, 3000);
  setInterval(refrescarContadores, 30000);

  if (token) entrar(token).catch((err) => salir(err.message));
  else salir();

  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});
});
