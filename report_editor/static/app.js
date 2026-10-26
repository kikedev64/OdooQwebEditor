"use strict";
const $ = id => document.getElementById(id);
const state = {mode: "demo", templates: [], fields: [], reports: [], reportId: null, templateId: null, revision: "", saved: "", selected: null, history: [], historyIndex: -1, previewVersion: 0, loading: false};
let debounceTimer, toastTimer, inputHistoryTimer;
const blocks = [
  {name: "Texto", icon: "T", xml: '<p style="font-size:14px;line-height:1.6;">Escribe aquí tu texto</p>'},
  {name: "Título", icon: "H₁", xml: '<h2 style="font-size:24px;color:#d9363e;">Nuevo título</h2>'},
  {name: "Dos columnas", icon: "▥", xml: '<div style="display:flex;gap:24px;margin:16px 0;"><div style="width:50%;"><p>Primera columna</p></div><div style="width:50%;"><p>Segunda columna</p></div></div>'},
  {name: "Tabla", icon: "▦", xml: '<table style="width:100%;border-collapse:collapse;margin:16px 0;"><thead><tr style="background:#fff0f1;"><th style="padding:12px;text-align:left;">Concepto</th><th style="padding:12px;text-align:right;">Importe</th></tr></thead><tbody><tr><td style="padding:12px;border-bottom:1px solid #eee;">Descripción</td><td style="padding:12px;text-align:right;border-bottom:1px solid #eee;">0,00 €</td></tr></tbody></table>'},
  {name: "Separador", icon: "―", xml: '<hr style="border:0;border-top:1px solid #e3e5ed;margin:24px 0;"/>'},
  {name: "Espaciador", icon: "↕", xml: '<div style="height:32px;"/>'},
  {name: "Imagen", icon: "▧", xml: `<img src="${location.origin}/static/placeholder.svg" alt="Sustituye src por la URL de tu imagen" style="width:180px;height:100px;object-fit:contain;"/>`},
  {name: "Nota", icon: "≡", xml: '<div style="background:#fff0f1;border-left:3px solid #d9363e;padding:16px;margin:16px 0;font-size:12px;"><strong>Información adicional</strong><p>Añade aquí las condiciones de tu documento.</p></div>'}
];

async function api(path, data) {
  const response = await fetch(`/api/${path}`, {method: data === undefined ? "GET" : "POST", headers: {"Content-Type": "application/json", "X-Editor-Request": "1"}, ...(data === undefined ? {} : {body: JSON.stringify(data)})});
  const result = await response.json();
  if (!response.ok) { const exc = new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail)); exc.diagnostic = result.diagnostic; throw exc; }
  return result;
}
function error(exc) {
  state.lastDiagnostic = exc.diagnostic;
  const titles = {missing_field: "La plantilla utiliza un campo que falta en Odoo", schema_error: "El código y la base de datos no coinciden", template_error: "El informe contiene un error de renderizado", query_timeout: "La búsqueda ha tardado demasiado"};
  $("error-title").textContent = titles[exc.diagnostic?.kind] || "No se ha podido completar la operación";
  $("error-message").textContent = exc.message || String(exc);
  $("error-details").hidden = !exc.diagnostic?.trace;
  $("error-trace").textContent = exc.diagnostic?.trace || "";
  $("locate-error").hidden = !exc.diagnostic?.field;
  $("error").hidden = false;
}
function toast(message) { $("toast").textContent = message; $("toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $("toast").hidden = true, 3200); }
function run(action) { return (...args) => Promise.resolve().then(() => action(...args)).catch(error); }
function dirty() { return $("source").value !== state.saved; }
function updateDirty() { $("dirty-dot").hidden = !dirty(); $("save-button").textContent = "Guardar XML" + (dirty() ? " •" : ""); }
function options(select, rows, label, empty) {
  select.replaceChildren();
  if (empty !== undefined) select.add(new Option(empty, ""));
  rows.forEach(row => select.add(new Option(label(row), row.id)));
}

class SearchPicker {
  constructor(kind, label, choose, fetchRows = null) {
    this.kind = kind; this.input = $(`${kind}-search`); this.list = $(`${kind}-results`);
    this.toggle = this.input.parentElement.querySelector("button"); this.label = label;
    this.onChoose = choose; this.fetchRows = fetchRows; this.rows = []; this.resultRows = []; this.version = 0; this.active = -1;
    this.input.onfocus = () => { this.input.select(); this.show(""); };
    this.input.oninput = () => {
      clearTimeout(this.timer); this.version++; this.resultRows = []; this.active = -1;
      this.list.hidden = false; this.list.textContent = "Buscando…"; this.input.setAttribute("aria-expanded", "true");
      if (fetchRows) this.timer = setTimeout(() => this.show(this.input.value), 220); else this.show(this.input.value);
    };
    this.input.onclick = () => { if (this.list.hidden) this.show(""); };
    this.toggle.onclick = () => {
      if (!this.list.hidden) { this.close(); return; }
      if (document.activeElement === this.input) this.show(""); else this.input.focus();
    };
    this.input.onblur = () => setTimeout(() => { if (!this.input.parentElement.contains(document.activeElement)) { this.close(); if (this.selected) this.input.value = this.label(this.selected); } }, 120);
    this.input.onkeydown = event => {
      if (event.key === "Escape") { this.close(); if (this.selected) this.input.value = this.label(this.selected); }
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault(); if (this.list.hidden) { this.show(""); return; }
        this.active = Math.max(0, Math.min(this.resultRows.length - 1, this.active + (event.key === "ArrowDown" ? 1 : -1)));
        this.highlight();
      }
      if (event.key === "Enter") { event.preventDefault(); if (this.active >= 0 && this.resultRows[this.active]) this.choose(this.resultRows[this.active]).catch(error); }
    };
  }
  reset(rows = [], placeholder = "Buscar…", disabled = false) {
    this.close(); clearTimeout(this.timer); this.selected = null; this.rows = rows;
    this.input.value = ""; this.input.placeholder = placeholder; this.input.disabled = disabled; this.toggle.disabled = disabled;
  }
  close() { this.version++; this.list.hidden = true; this.input.setAttribute("aria-expanded", "false"); this.input.removeAttribute("aria-activedescendant"); }
  async show(query) {
    if (this.input.disabled) return;
    const version = ++this.version; this.list.hidden = false; this.input.setAttribute("aria-expanded", "true");
    this.resultRows = []; this.active = -1;
    this.list.textContent = "Buscando…";
    try {
      const rows = this.fetchRows ? await this.fetchRows(query) : this.rows.filter(row => this.label(row).toLowerCase().includes(query.toLowerCase()));
      if (version !== this.version) return;
      this.resultRows = rows; this.active = -1; this.list.replaceChildren();
      if (!rows.length) { this.list.textContent = "Sin resultados. Prueba otro nombre, ID o referencia."; return; }
      rows.forEach((row, index) => {
        const button = document.createElement("button"); button.type = "button"; button.role = "option";
        button.id = `${this.kind}-option-${index}`; button.textContent = this.label(row); button.setAttribute("aria-selected", "false");
        button.onmousedown = event => event.preventDefault(); button.onclick = () => this.choose(row).catch(error);
        this.list.append(button);
      });
    } catch (exc) { if (version === this.version) { this.list.textContent = "No se pudo cargar el listado."; error(exc); } }
  }
  highlight() {
    [...this.list.children].forEach((node, index) => node.setAttribute("aria-selected", String(index === this.active)));
    const option = this.list.children[this.active];
    if (option) { this.input.setAttribute("aria-activedescendant", option.id); option.scrollIntoView({block: "nearest"}); }
  }
  async choose(row) {
    const previous = this.selected; this.selected = row; this.input.value = this.label(row); this.close();
    try { if (await this.onChoose(row) === false) { this.selected = previous; this.input.value = previous ? this.label(previous) : ""; } }
    catch (exc) { error(exc); }
  }
}

const modelPicker = new SearchPicker("model", row => `${row.name} (${row.id})`, chooseModel);
const reportPicker = new SearchPicker("report", row => `${row.name} - ${row.key}`, chooseReport);
const recordPicker = new SearchPicker("record", row => `#${row.id} · ${row.display_name}`, async row => {
  state.recordId = row.id; clearPreview("Preparando registro…"); await preview();
}, query => api(`records?model=${encodeURIComponent(state.model)}&q=${encodeURIComponent(query)}`));

function clearPreview(message) {
  $("pdf-preview").hidden = true; $("pdf-preview").removeAttribute("src");
  state.previewVersion++; $("preview").srcdoc = ""; $("paper-wrapper").hidden = true; $("preview-empty").hidden = false;
  $("preview-empty").querySelector("p").textContent = message; $("preview-status").textContent = message; $("render-time").textContent = "";
  $("placeholder-warning").hidden = true;
  $("resource-warning").hidden = true;
}
function resetEditor(message) {
  clearTimeout(debounceTimer); clearTimeout(inputHistoryTimer); state.selectionVersion = (state.selectionVersion || 0) + 1;
  state.templateId = null; state.saved = ""; state.revision = ""; state.history = []; state.historyIndex = -1;
  state.templates = []; $("source").value = ""; $("filename").textContent = ""; options($("template"), [], () => "", "Selecciona un informe"); $("template").disabled = true;
  $("error").hidden = true; selectElement(null); lineNumbers(); updateDirty(); clearPreview(message);
}
async function chooseModel(row) {
  if (dirty() && !confirm("¿Descartar el borrador y cambiar de modelo?")) return false;
  state.model = row.id; state.reportId = null; state.recordId = null;
  state.fields = []; renderFields();
  resetEditor("Selecciona un informe y un registro de ejemplo.");
  reportPicker.reset(state.reports.filter(report => report.model === row.id), "Buscar informe por nombre o plantilla…");
  recordPicker.reset([], "Selecciona primero un informe", true);
  await loadFields();
}
async function chooseReport(row) {
  if (dirty() && !confirm("¿Descartar el borrador y abrir otro informe?")) return false;
  state.reportId = row.id; state.recordId = null;
  $("preview-mode").querySelector('[value="pdf"]').disabled = state.mode === "demo" || row.report_type === "qweb-html";
  if (row.report_type === "qweb-html") $("preview-mode").value = "html";
  updatePreviewMode();
  resetEditor("Busca y selecciona un registro de ejemplo.");
  recordPicker.reset([], "Buscar por ID, nombre, referencia o cliente…");
  await loadTemplates();
}
function xmlDocument(source = $("source").value) {
  const doc = new DOMParser().parseFromString(source, "application/xml");
  if (doc.querySelector("parsererror")) throw new Error("El XML no es válido. Corrige el código antes de editar visualmente.");
  return doc;
}
function nodes(doc) { return [doc.documentElement, ...doc.documentElement.querySelectorAll("*")]; }
function selectedNode(doc) { return state.selected === null ? null : nodes(doc)[state.selected]; }
function serialize(doc) { return new XMLSerializer().serializeToString(doc); }
function pushHistory() {
  clearTimeout(inputHistoryTimer);
  const value = $("source").value;
  if (state.history[state.historyIndex] === value) return;
  state.history = state.history.slice(0, state.historyIndex + 1);
  state.history.push(value);
  if (state.history.length > 100) state.history.shift();
  state.historyIndex = state.history.length - 1;
}
function lineNumbers() {
  $("line-numbers").textContent = Array.from({length: $("source").value.split("\n").length}, (_, i) => i + 1).join("\n");
  $("line-numbers").scrollTop = $("source").scrollTop;
  cursorPosition();
}
function cursorPosition() {
  const before = $("source").value.slice(0, $("source").selectionStart).split("\n");
  $("cursor-position").textContent = `Línea ${before.length}, Col ${before.at(-1).length + 1}`;
}
function sourceChanged({history = true, resetSelection = true} = {}) {
  if (history) pushHistory();
  if (resetSelection) selectElement(null);
  state.previewVersion++;
  lineNumbers(); updateDirty();
  try { xmlDocument(); $("xml-status").textContent = "✓ XML válido"; } catch { $("xml-status").textContent = "! XML inválido"; }
  clearTimeout(debounceTimer);
  if ($("live").checked) debounceTimer = setTimeout(() => preview().catch(error), 550);
  else $("preview-status").textContent = "Cambios pendientes de previsualizar";
}
function mutate(fn, preserveSelection = false) {
  pushHistory();
  const doc = xmlDocument();
  fn(doc);
  $("source").value = serialize(doc);
  sourceChanged({resetSelection: !preserveSelection});
  if (preserveSelection) selectElement(state.selected);
}
function insertXML(xml, target = state.selected) {
  const fragment = xmlDocument(xml).documentElement;
  mutate(doc => {
    const element = doc.importNode(fragment, true);
    const selected = target === null ? null : nodes(doc)[target];
    if (!selected || selected === doc.documentElement) {
      const page = doc.querySelector(".page") || doc.querySelector("[t-foreach]") || doc.documentElement;
      page.append(doc.createTextNode("\n    "), element, doc.createTextNode("\n"));
    } else {
      const position = $("insert-position").value;
      if (position === "inside") {
        if (["img", "hr", "br", "input"].includes(selected.tagName) || selected.hasAttribute("t-field") || selected.hasAttribute("t-out")) throw new Error("Este elemento no admite contenido. Selecciona un contenedor o inserta antes/después.");
        selected.append(doc.createTextNode("\n"), element);
      } else if (position === "before") selected.before(element, doc.createTextNode("\n"));
      else selected.after(doc.createTextNode("\n"), element);
    }
  });
}
function renderFields() {
  $("fields").replaceChildren();
  const query = $("field-search").value.toLowerCase();
  state.fields.filter(f => `${f.name} ${f.string}`.toLowerCase().includes(query)).forEach(field => {
    const button = document.createElement("button"); button.className = "field"; button.draggable = true;
    const icon = document.createElement("span"); icon.textContent = field.type === "monetary" ? "€" : "ƒ";
    const label = document.createElement("span"); label.textContent = field.string;
    const key = document.createElement("small"); key.textContent = field.name; label.append(key); button.append(icon, label);
    const xml = () => `<span t-field="${documentAlias()}.${field.name}"/>`;
    button.addEventListener("click", run(() => insertXML(xml())));
    button.addEventListener("dragstart", event => { event.dataTransfer.setData("application/x-qweb-block", xml()); event.dataTransfer.effectAllowed = "copy"; });
    $("fields").append(button);
  });
}
function documentAlias() {
  const source = $("source").value, counts = {o: 0, doc: 0};
  for (const match of source.matchAll(/t-(?:field|esc|out)=["'](o|doc)\./g)) counts[match[1]]++;
  if (counts.o || counts.doc) return counts.doc > counts.o ? "doc" : "o";
  try {
    const loop = xmlDocument().querySelector('[t-foreach="docs"][t-as]');
    if (loop) return loop.getAttribute("t-as");
  } catch {  }
  return "o";
}
blocks.forEach(block => {
  const button = document.createElement("button"); button.className = "block"; button.draggable = true;
  const icon = document.createElement("span"); icon.className = "block-icon"; icon.textContent = block.icon;
  button.append(icon, document.createTextNode(block.name));
  button.addEventListener("click", run(() => insertXML(block.xml)));
  button.addEventListener("dragstart", event => { event.dataTransfer.setData("application/x-qweb-block", block.xml); event.dataTransfer.effectAllowed = "copy"; });
  $("blocks").append(button);
});

async function loadTemplates() {
  const version = state.selectionVersion;
  const rows = await api(`templates?report_id=${state.reportId}`);
  if (version !== state.selectionVersion) return;
  state.templates = rows;
  options($("template"), rows, row => row.key || row.name, rows.length ? undefined : "Sin plantillas editables");
  $("template").disabled = !rows.length;
  if (rows.length) await loadTemplate();
}
async function loadFields() {
  const model = state.model;
  if (!model) { state.fields = []; renderFields(); return; }
  const fields = await api(`fields?model=${encodeURIComponent(model)}`);
  if (model !== state.model) return;
  state.fields = fields; renderFields();
}
async function loadTemplate(render = true) {
  const id = Number($("template").value); if (!id) return;
  const version = state.selectionVersion;
  const template = await api(`templates/${id}`);
  if (version !== state.selectionVersion || Number($("template").value) !== id) return;
  clearTimeout(debounceTimer); state.previewVersion++;
  state.templateId = id; state.revision = template.revision; state.saved = template.source;
  state.history = []; state.historyIndex = -1;
  $("source").value = template.source; $("filename").textContent = template.key || template.name;
  selectElement(null); pushHistory(); lineNumbers(); updateDirty();
  if (render && state.recordId) await preview();
}
function selectionId(element) {
  const candidate = element?.closest?.("[data-editor-node]");
  return candidate ? Number(candidate.getAttribute("data-editor-node")) : null;
}
function selectElement(index) {
  state.selected = index;
  let element;
  try { element = selectedNode(xmlDocument()); } catch { element = null; }
  const hasValue = element?.hasAttribute("t-field") || element?.hasAttribute("t-out") || element?.hasAttribute("t-esc");
  $("selected-label").textContent = element ? `<${element.tagName}>${element.getAttribute("t-field") ? " · " + element.getAttribute("t-field") : ""}` : "Ninguno";
  $("element-text").disabled = !element || !!element.children.length;
  $("element-text").placeholder = hasValue ? "Expression QWeb (o.name)" : "Texto del elemento";
  $("element-text").value = element && !element.children.length ? element.getAttribute("t-field") || element.getAttribute("t-out") || element.getAttribute("t-esc") || element.textContent : "";
  const styles = document.createElement("div"); styles.setAttribute("style", element?.getAttribute("style") || "");
  for (const [id, prop] of [["element-color", "color"], ["element-size", "fontSize"], ["element-padding", "padding"]]) { $(id).disabled = !element; $(id).value = styles.style[prop]; }
  try {
    const previewDoc = $("preview").contentDocument;
    previewDoc?.querySelectorAll("[data-editor-selected]").forEach(e => e.removeAttribute("data-editor-selected"));
    if (index !== null) previewDoc?.querySelectorAll(`[data-editor-node="${index}"]`).forEach(e => e.setAttribute("data-editor-selected", "1"));
  } catch {  }
}
function revealSource(index) {
  const editor = $("source"), range = templateRanges(editor.value)[index];
  if (!range || state.renderedSource !== editor.value) return;
  editor.focus({preventScroll: true});
  editor.setSelectionRange(range.start, range.openEnd);
  const line = editor.value.slice(0, range.start).split("\n").length - 1;
  editor.scrollTop = Math.max(0, (line - 3) * parseFloat(getComputedStyle(editor).lineHeight));
  editor.scrollLeft = 0;
  $("line-numbers").scrollTop = editor.scrollTop;
  cursorPosition();
}
function revealPreviewFromSource() {
  cursorPosition();
  const editor = $("source");
  if (state.renderedSource !== editor.value) return;
  const offset = editor.selectionStart;
  const range = templateRanges(editor.value).filter(item => item.start <= offset && offset < item.end).at(-1);
  if (!range) return;
  const doc = $("preview").contentDocument;
  let index = range.index;
  if (!doc?.querySelector(`[data-editor-node="${index}"]`)) {
    const descendants = templateRanges(editor.value).filter(item => item.start >= range.start && item.end <= range.end);
    index = descendants.find(item => doc?.querySelector(`[data-editor-node="${item.index}"]`))?.index ?? null;
  }
  selectElement(index);
  if (index === null) return;
  const matches = [...doc.querySelectorAll(`[data-editor-node="${index}"]`)];
  for (const element of matches) {
    const viewport = element.closest('.editor-page-viewport');
    const bounds = viewport?.getBoundingClientRect();
    const rect = [...element.getClientRects()].find(rect => !bounds || (rect.right > bounds.left && rect.left < bounds.right && rect.bottom > bounds.top && rect.top < bounds.bottom));
    if (!rect) continue;
    const zoom = parseFloat($("preview").dataset.zoom || 1);
    const scroller = $("preview-scroll"), wrapper = $("paper-wrapper");
    scroller.scrollTop = wrapper.offsetTop + rect.top * zoom - scroller.clientHeight / 3;
    break;
  }
}
function moveElement(from, to) {
  if (from === to || to === null) return;
  mutate(doc => {
    const elements = nodes(doc), source = elements[from], target = elements[to];
    if (!source || !target || source === doc.documentElement || source.contains(target)) throw new Error("No puedes mover un contenedor dentro de sí mismo.");
    const position = $("insert-position").value;
    if (position === "inside") {
      if (["img", "hr", "br", "input"].includes(target.tagName) || target.hasAttribute("t-field") || target.hasAttribute("t-out")) throw new Error("Este elemento no admite contenido.");
      target.append(source);
    } else if (target === doc.documentElement) throw new Error("No se puede colocar contenido fuera de la raíz XML.");
    else if (position === "before") target.before(source);
    else target.after(source);
  });
}
function attachPreview() {
  const doc = $("preview").contentDocument;
  if (!doc) return;
  const pages = new ReportPages(doc, state.paper);
  const repaginate = () => {
    if (doc !== $("preview").contentDocument) return;
    const count = pages.layout();
    $("page-count").textContent = `A4 · ${count} ${count === 1 ? "página" : "páginas"}`;
    selectElement(state.selected); resizePaper();
  };
  repaginate();
  doc.querySelectorAll("[data-editor-node]").forEach(element => {
    element.draggable = false;
  });
  let moving = null;
  doc.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    const index = selectionId(event.target);
    if (index === null) return;
    event.preventDefault(); selectElement(index);
    moving = {index, x: event.clientX, y: event.clientY, dragged: false};
    doc.documentElement.setPointerCapture(event.pointerId);
  });
  doc.addEventListener("pointermove", event => {
    if (!moving) return;
    if (Math.hypot(event.clientX - moving.x, event.clientY - moving.y) > 6) moving.dragged = true;
    doc.querySelectorAll("[data-editor-drop]").forEach(element => element.removeAttribute("data-editor-drop"));
    const target = doc.elementFromPoint(event.clientX, event.clientY)?.closest("[data-editor-node]");
    if (moving.dragged && target && selectionId(target) !== moving.index) target.setAttribute("data-editor-drop", "1");
  });
  doc.addEventListener("pointerup", event => {
    if (!moving) return;
    const from = moving, target = selectionId(doc.elementFromPoint(event.clientX, event.clientY));
    moving = null;
    if (doc.documentElement.hasPointerCapture(event.pointerId)) doc.documentElement.releasePointerCapture(event.pointerId);
    doc.querySelectorAll("[data-editor-drop]").forEach(element => element.removeAttribute("data-editor-drop"));
    if (from.dragged) run(() => moveElement(from.index, target))();
    else revealSource(from.index);
  });
  doc.addEventListener("pointercancel", () => { moving = null; });
  doc.addEventListener("dragstart", event => event.preventDefault());
  doc.addEventListener("click", event => {
    event.preventDefault(); event.stopPropagation();
    if (event.detail === 0) { const index = selectionId(event.target); selectElement(index); if (index !== null) revealSource(index); }
  });
  doc.addEventListener("dragover", event => { event.preventDefault(); event.dataTransfer.dropEffect = event.dataTransfer.types.includes("application/x-qweb-node") ? "move" : "copy"; });
  doc.addEventListener("drop", event => {
    event.preventDefault(); event.stopPropagation();
    run(() => {
    const id = selectionId(event.target);
    const xml = event.dataTransfer.getData("application/x-qweb-block"), from = event.dataTransfer.getData("application/x-qweb-node");
    if (xml) insertXML(xml, id);
    else if (from !== "") moveElement(Number(from), id);
    })();
  });
  selectElement(state.selected); resizePaper();
  const loadedResources = new Set();
  doc.addEventListener('load', event => {
    if (!event.target.matches?.('img,link')) return;
    const key = event.target.currentSrc || event.target.href;
    if (loadedResources.has(key)) return;
    loadedResources.add(key); scheduleLayout();
  }, true);
  let layoutTimer;
  const scheduleLayout = () => { clearTimeout(layoutTimer); layoutTimer = setTimeout(repaginate, 80); };
  doc.fonts?.ready.then(scheduleLayout);
}
function resizePaper() {
  const frame = $("preview");
  const zoom = $("zoom").value === "fit" ? Math.max(0.2, Math.min(1, ($("preview-scroll").clientWidth - 44) / A4.width)) : Number($("zoom").value);
  let height = A4.height;
  try { const count = frame.contentDocument.querySelectorAll('.editor-sheet').length || 1; height = count * A4.height + (count - 1) * A4.gap; } catch {  }
  frame.dataset.zoom = zoom;
  frame.style.width = `${A4.width}px`;
  frame.style.height = `${height}px`; frame.style.transform = `scale(${zoom})`;
  $("paper-wrapper").style.width = `${A4.width * zoom}px`;
  $("paper-wrapper").style.height = `${height * zoom}px`;
}
function previewDocument(html, baseURL) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll("script,iframe,object,embed,base,meta[http-equiv]").forEach(node => node.remove());
  const csp = doc.createElement("meta"); csp.httpEquiv = "Content-Security-Policy";
  csp.content = "script-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri http: https:;";
  doc.head.prepend(csp);
  if (baseURL) { const base = doc.createElement("base"); base.href = `${baseURL}/`; csp.after(base); }
  const style = doc.createElement("style"); style.textContent = '*{box-sizing:border-box}[data-editor-node]:hover{outline:1px dashed #e79ba2;outline-offset:2px;cursor:grab}[data-editor-selected]{outline:2px solid #d9363e!important;outline-offset:3px}[data-editor-drop]{outline:2px dashed #d9363e!important;background-color:#fff0f1!important}[data-editor-placeholder]{color:#b85b26;background:#fff1dc;border-bottom:1px dashed #c88f52}';
  doc.head.append(style);
  return '<!doctype html>' + doc.documentElement.outerHTML;
}
async function preview() {
  clearTimeout(debounceTimer);
  if (!state.templateId || !state.recordId || !state.model) { $("preview-status").textContent = "Selecciona un modelo y un registro"; return; }
  if (state.previewBusy) { state.previewQueued = true; state.previewVersion++; return; }
  state.previewBusy = true;
  const version = ++state.previewVersion, start = performance.now();
  $("preview-status").textContent = "Renderizando…";
  try {
    const result = await api("preview", {template_id: state.templateId, record_id: state.recordId, source: $("source").value, model: state.model, report_id: state.mode === "demo" ? null : state.reportId, placeholders: $("placeholders").checked, format: $("preview-mode").value});
    if (version !== state.previewVersion) return;
    state.paper = result.paper || {};
    state.renderedSource = $("source").value;
    $("paper-wrapper").hidden = !!result.pdf_url; $("preview-empty").hidden = true;
    $("pdf-preview").hidden = !result.pdf_url;
    if (result.pdf_url) {
      $("pdf-preview").src = result.pdf_url;
      $("page-count").textContent = "Formato y paginación de Odoo";
    } else {
      $("pdf-preview").removeAttribute("src");
      $("preview").srcdoc = previewDocument(result.html, result.base_url);
    }
    $("preview-status").textContent = result.pdf_url ? "PDF de Odoo actualizado" : "Vista de edición actualizada";
    const resources = result.resource_warnings || [];
    $("resource-warning").hidden = !resources.length;
    $("resource-warning").textContent = resources.length ? `No se pudieron cargar ${resources.length} recursos: ${resources.map(item => item.url).join(", ")}` : "";
    const warnings = result.warnings || [];
    $("placeholder-warning").hidden = !warnings.length;
    $("placeholder-summary").textContent = `Vista de ejemplo · ${warnings.length} sustituciones de campos ausentes`;
    $("placeholder-list").replaceChildren();
    warnings.forEach(warning => { const item = document.createElement("li"); item.textContent = `${warning.field} · ${warning.template}`; $("placeholder-list").append(item); });
    $("render-time").textContent = `${Math.round(performance.now() - start)} ms`;
    $("error").hidden = true;
  } catch (exc) {
    if (version !== state.previewVersion) return;
    $("preview-status").textContent = "Error · Se conserva la última vista válida";
    throw exc;
  } finally {
    state.previewBusy = false;
    if (state.previewQueued) { state.previewQueued = false; preview().catch(error); }
  }
}
function download(source, name) {
  const blob = new Blob([source], {type: "application/xml;charset=utf-8"});
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = name;
  link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
async function save() {
  if ($("save-button").disabled) return;
  xmlDocument();
  const source = $("source").value, templateId = state.templateId;
  if (!templateId) throw new Error("Selecciona un informe y una plantilla antes de guardar.");
  $("save-button").disabled = true;
  try {
    const result = await api("save", {template_id: templateId, source, revision: state.revision});
    if (templateId !== state.templateId) return;
    state.revision = result.revision; state.saved = source; updateDirty();
    toast(`XML guardado: ${result.path}`);
  } finally { $("save-button").disabled = false; }
}
async function initialize() {
  const status = await api("status"); state.mode = status.mode;
  $("placeholders").checked = state.mode === "demo";
  $("preview-mode").value = state.mode === "demo" ? "html" : "pdf";
  $("preview-mode").querySelector('[value="pdf"]').disabled = state.mode === "demo";
  updatePreviewMode();
  options($("database"), (status.databases || []).map(name => ({id: name})), row => row.id, state.mode === "demo" ? "Demostración" : "Selecciona una base de datos");
  $("database").value = status.database || ""; $("database").disabled = state.mode === "demo";
  state.model = null; state.reportId = null; state.recordId = null; state.fields = []; renderFields();
  resetEditor("Selecciona un modelo, un informe y un registro de ejemplo.");
  reportPicker.reset([], "Selecciona primero un modelo", true); recordPicker.reset([], "Selecciona primero un informe", true);
  modelPicker.reset([], "Cargando modelos…", true);
  if (state.mode === "docker" && !status.database) { clearPreview("Selecciona una base de datos para empezar."); return; }
  state.reports = await api("reports");
  const models = [...new Map(state.reports.map(report => [report.model, {id: report.model, name: report.model_name || report.model}])).values()].sort((a,b) => a.name.localeCompare(b.name));
  modelPicker.reset(models, "Buscar modelo por nombre…");
}

$("preview").addEventListener("load", attachPreview);
$("source").addEventListener("input", () => { sourceChanged({history: false}); clearTimeout(inputHistoryTimer); inputHistoryTimer = setTimeout(pushHistory, 450); });
$("source").addEventListener("scroll", () => $("line-numbers").scrollTop = $("source").scrollTop);
$("source").addEventListener("click", revealPreviewFromSource); $("source").addEventListener("keyup", revealPreviewFromSource);
$("source").addEventListener("keydown", event => {
  if (event.key === "Tab") { event.preventDefault(); const source = $("source"); source.setRangeText("  ", source.selectionStart, source.selectionEnd, "end"); sourceChanged(); }
});
$("template").addEventListener("change", run(async () => {
  if (dirty() && !confirm("Hay cambios sin guardar. ¿Descartarlos y abrir otra plantilla?")) { $("template").value = state.templateId; return; }
  await loadTemplate();
}));
$("database").onchange = run(async () => {
  if (!$("database").value) return;
  if (dirty() && !confirm("¿Descartar el borrador y cambiar de base de datos?")) { const status = await api("status"); $("database").value = status.database || ""; return; }
  await api("database", {database: $("database").value});
  await initialize();
});
$("field-search").oninput = renderFields;
$("refresh").onclick = run(preview);
function updatePreviewMode() {
  const pdf = $("preview-mode").value === "pdf";
  $("zoom").disabled = pdf;
  $("preview-help").textContent = pdf ? "PDF generado por Odoo con el borrador actual." : "Selecciona un elemento para editarlo. Paginación aproximada.";
}
$("preview-mode").onchange = run(async () => {
  updatePreviewMode();
  clearPreview("Actualizando vista…");
  if (state.recordId) await preview();
});
$("placeholders").onchange = run(preview);
$("live").onchange = () => { if ($("live").checked) preview().catch(error); else clearTimeout(debounceTimer); };
$("zoom").onchange = resizePaper;
$("save-button").onclick = run(save);
$("export-button").onclick = () => download($("source").value, `${$("filename").textContent || "template"}.xml`);
$("about-button").onclick = () => $("about-dialog").showModal();
$("close-about").onclick = () => $("about-dialog").close();
$("about-dialog").addEventListener('click', event => { if (event.target === $("about-dialog") && (event.offsetX < 0 || event.offsetX > event.target.clientWidth || event.offsetY < 0 || event.offsetY > event.target.clientHeight)) event.target.close(); });
$("toggle-tools").onclick = () => {
  const collapsed = document.body.classList.toggle('tools-collapsed');
  $("toggle-tools").textContent = collapsed ? '›' : '‹';
  $("toggle-tools").setAttribute('aria-expanded', String(!collapsed));
  $("toggle-tools").setAttribute('aria-label', collapsed ? 'Mostrar bloques y campos' : 'Plegar bloques y campos');
  $("toggle-tools").title = $("toggle-tools").getAttribute('aria-label');
  localStorage.setItem('qweb-tools-collapsed', String(collapsed));
};
if (localStorage.getItem('qweb-tools-collapsed') === 'true') $("toggle-tools").click();
$("undo").onclick = () => { pushHistory(); if (state.historyIndex > 0) { $("source").value = state.history[--state.historyIndex]; sourceChanged({history: false}); } };
$("redo").onclick = () => { if (state.historyIndex < state.history.length - 1) { $("source").value = state.history[++state.historyIndex]; sourceChanged({history: false}); } };
$("format").onclick = run(() => {
  mutate(doc => {
    const indent = (element, depth) => {
      if (!element.children.length) return;
      const mixed = Array.from(element.childNodes).some(n => n.nodeType === 3 && n.textContent.trim());
      Array.from(element.children).forEach(child => indent(child, depth + 1));
      if (mixed) return;
      Array.from(element.childNodes).filter(n => n.nodeType === 3 && !n.textContent.trim()).forEach(n => n.remove());
      Array.from(element.childNodes).forEach(child => element.insertBefore(doc.createTextNode("\n" + "  ".repeat(depth + 1)), child));
      element.append(doc.createTextNode("\n" + "  ".repeat(depth)));
    };
    indent(doc.documentElement, 0);
  });
});
$("element-text").onchange = run(() => { const value = $("element-text").value; mutate(doc => { const element = selectedNode(doc); if (!element) return; const attr = ["t-field", "t-out", "t-esc"].find(name => element.hasAttribute(name)); if (attr) element.setAttribute(attr, value); else if (!element.children.length) element.textContent = value; }, true); });
for (const [id, prop] of [["element-color", "color"], ["element-size", "font-size"], ["element-padding", "padding"]]) {
  $(id).onchange = run(() => { const value = $(id).value; mutate(doc => { const element = selectedNode(doc); if (!element) return; const styles = document.createElement("div"); styles.setAttribute("style", element.getAttribute("style") || ""); if (value) { if (!CSS.supports(prop, value)) throw new Error(`Valor CSS inválido: ${value}`); styles.style.setProperty(prop, value); } else styles.style.removeProperty(prop); element.setAttribute("style", styles.getAttribute("style") || ""); }, true); });
}
$("move-up").onclick = run(() => mutate(doc => { const element = selectedNode(doc); if (element?.previousElementSibling) element.previousElementSibling.before(element); }));
$("move-down").onclick = run(() => mutate(doc => { const element = selectedNode(doc); if (element?.nextElementSibling) element.nextElementSibling.after(element); }));
$("delete-element").onclick = run(() => { if (state.selected === null) return; mutate(doc => { const element = selectedNode(doc); if (element === doc.documentElement) throw new Error("No se puede eliminar la raíz de la plantilla."); element?.remove(); }); });
$("dismiss-error").onclick = () => $("error").hidden = true;
$("locate-error").onclick = run(async () => {
  const diagnostic = state.lastDiagnostic; if (!diagnostic) return;
  const target = state.templates.find(row => row.key === diagnostic.template);
  if (target && target.id !== state.templateId) {
    if (dirty() && !confirm("¿Descartar el borrador y abrir la plantilla que contiene el error?")) return;
    $("template").value = target.id; await loadTemplate(false);
  }
  const editor = $("source"), offset = editor.value.indexOf(`.${diagnostic.field}`);
  if (offset < 0) { toast("El campo está en otra plantilla o vista heredada del informe."); return; }
  editor.focus(); editor.setSelectionRange(offset + 1, offset + 1 + diagnostic.field.length);
  editor.scrollTop = Math.max(0, (editor.value.slice(0, offset).split("\n").length - 4) * 22);
  cursorPosition(); $("error").hidden = true;
});
document.addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); save().catch(error); } if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); preview().catch(error); } });
window.addEventListener("beforeunload", event => { if (dirty()) { event.preventDefault(); event.returnValue = ""; } });
const handle = $("split-handle");
handle.addEventListener("pointerdown", event => { handle.setPointerCapture(event.pointerId); document.body.classList.add("resizing"); });
handle.addEventListener("pointermove", event => { if (!handle.hasPointerCapture(event.pointerId)) return; const bounds = $("source").closest(".editor-workspace").getBoundingClientRect(); const width = Math.max(28, Math.min(70, (event.clientX - bounds.left) / bounds.width * 100)); document.querySelector(".editor-pane").style.width = `${width}%`; });
handle.addEventListener("pointerup", event => { handle.releasePointerCapture(event.pointerId); document.body.classList.remove("resizing"); });
handle.addEventListener("keydown", event => { if (["ArrowLeft", "ArrowRight"].includes(event.key)) { event.preventDefault(); const pane = document.querySelector(".editor-pane"), width = pane.clientWidth / pane.parentElement.clientWidth * 100; pane.style.width = `${Math.max(28, Math.min(70, width + (event.key === "ArrowRight" ? 3 : -3)))}%`; } });
new ResizeObserver(resizePaper).observe($("preview-scroll"));
initialize().catch(error);
