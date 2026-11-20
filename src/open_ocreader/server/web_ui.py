"""
Interfaz Web Responsiva y Accesible 100% Offline (cero dependencias CDN)
para acceder a Open OCReader Server desde navegadores de PC, tablet o móvil Android/iOS.
"""

WEB_UI_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Open OCReader Web — OCR e IA Documental 100% Local</title>
  <style>
    :root {
      --bg: #f4f6f9;
      --card: #ffffff;
      --fg: #181a1f;
      --muted: #525866;
      --accent: #1a5fb4;
      --accent-fg: #ffffff;
      --ok: #1b6e2e;
      --border: #cfd6e1;
      --input-bg: #ffffff;
      --focus: #1a5fb4;
      --scale: 1;
      --font-main: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      --line-h: 1.5;
      --letter-sp: normal;
    }
    [data-theme="hc-dark"] {
      --bg: #000000;
      --card: #0c0c0c;
      --fg: #ffffff;
      --muted: #ffff00;
      --accent: #00ffff;
      --accent-fg: #000000;
      --ok: #00ff66;
      --border: #00ffff;
      --input-bg: #111111;
      --focus: #ffff00;
    }
    [data-theme="dyslexia"] {
      --bg: #faf6eb;
      --card: #fffdf7;
      --fg: #1f1d1a;
      --muted: #575047;
      --accent: #0b4f6c;
      --accent-fg: #ffffff;
      --ok: #1b5e20;
      --border: #bcae8e;
      --input-bg: #fffdf7;
      --focus: #0b4f6c;
      --font-main: Verdana, Geneva, Tahoma, sans-serif;
      --line-h: 1.75;
      --letter-sp: 0.03em;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font-family: var(--font-main);
      font-size: calc(16px * var(--scale));
      line-height: var(--line-h);
      letter-spacing: var(--letter-sp);
    }
    .wrap { max-width: 980px; margin: 0 auto; padding: 14px; }
    .card {
      background: var(--card);
      border: 2px solid var(--border);
      border-radius: 10px;
      padding: 14px;
      margin-bottom: 12px;
    }
    header {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
    }
    h1 { font-size: 1.35em; margin: 0; }
    .sub { color: var(--muted); font-size: 0.85em; margin-top: 2px; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .col { display: flex; flex-direction: column; gap: 6px; }
    button, select, input[type="text"], input[type="password"] {
      font: inherit;
      color: var(--fg);
      background: var(--input-bg);
      border: 2px solid var(--border);
      border-radius: 7px;
      padding: 8px 12px;
      min-height: 42px;
    }
    button { cursor: pointer; font-weight: 600; }
    button.primary { background: var(--accent); color: var(--accent-fg); border-color: var(--accent); }
    button:focus, select:focus, input:focus, textarea:focus {
      outline: 3px solid var(--focus);
      outline-offset: 1px;
    }
    button:disabled { opacity: 0.55; cursor: wait; }
    .tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
    .tab-btn[aria-selected="true"] {
      background: var(--accent);
      color: var(--accent-fg);
      border-color: var(--accent);
    }
    .panel { display: none; }
    .panel.active { display: block; }
    .drop-area {
      display: block;
      border: 2px dashed var(--accent);
      border-radius: 8px;
      padding: 14px;
      text-align: center;
      cursor: pointer;
      margin-bottom: 10px;
    }
    label.chk { display: inline-flex; align-items: center; gap: 6px; min-height: 38px; cursor: pointer; }
    textarea.out {
      width: 100%;
      min-height: 220px;
      font: inherit;
      background: var(--input-bg);
      color: var(--fg);
      border: 2px solid var(--border);
      border-radius: 7px;
      padding: 10px;
      resize: vertical;
    }
    .ref-card {
      border-left: 4px solid var(--accent);
      padding: 8px 10px;
      margin-top: 8px;
      background: var(--bg);
      border-radius: 4px;
      font-size: 0.9em;
    }
    .status { font-weight: 600; color: var(--ok); margin-top: 8px; word-break: break-word; }
    .error { font-weight: 600; color: #dc2626; margin-top: 8px; word-break: break-word; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <header>
        <div>
          <h1>Open OCReader Web</h1>
          <div class="sub">Digitalización, Traducción e IA Documental 100% Local (Docker / Móvil / Intranet)</div>
        </div>
        <div class="row" role="toolbar" aria-label="Accesibilidad y zoom">
          <button type="button" onclick="setZoom(-0.1)" aria-label="Reducir letra">A-</button>
          <button type="button" onclick="resetZoom()" id="zoomLbl">100%</button>
          <button type="button" onclick="setZoom(0.1)" aria-label="Ampliar letra">A+</button>
          <button type="button" onclick="toggleTheme('hc-dark')">Alto Contraste AAA</button>
          <button type="button" onclick="toggleTheme('dyslexia')">Modo Dislexia</button>
          <button type="button" onclick="speakOut()">🔊 Leer</button>
          <button type="button" onclick="stopSpeak()">⏹️ Callar</button>
        </div>
      </header>
      <div class="row" style="margin-top:10px;">
        <label for="apiKey">🔑 Clave API (X-API-Key):</label>
        <input type="password" id="apiKey" placeholder="Opcional en localhost; obligatoria en red" style="flex:1;min-width:200px;" />
        <button type="button" onclick="saveKey()">Guardar</button>
        <button type="button" onclick="checkHealth()">Comprobar servidor</button>
      </div>
      <div id="healthStatus" class="sub" style="margin-top:4px;"></div>
    </div>

    <div class="card">
      <label class="drop-area" for="fileInput">
        <strong>📥 Toca aquí para seleccionar PDF/Imagen o usar cámara del móvil</strong><br/>
        <span id="fileName" class="sub">Ningún fichero seleccionado</span>
      </label>
      <input type="file" id="fileInput" accept=".pdf,image/*" capture="environment" style="display:none;" onchange="onFilePicked()" />

      <div class="tabs" role="tablist">
        <button type="button" class="tab-btn" role="tab" aria-selected="true" onclick="showTab(0)">📄 Convertir</button>
        <button type="button" class="tab-btn" role="tab" aria-selected="false" onclick="showTab(1)">🌐 Traducir Documento</button>
        <button type="button" class="tab-btn" role="tab" aria-selected="false" onclick="showTab(2)">🧠 IA, Lectura Fácil y Preguntas</button>
      </div>

      <!-- TAB 1: CONVERTIR -->
      <div id="tab0" class="panel active col">
        <div class="row">
          <label for="convFmt">Formato:</label>
          <select id="convFmt">
            <option value="pdf">PDF Buscable (Sandwich)</option>
            <option value="pdfa">PDF/A-2b (Archivo Público)</option>
            <option value="docx">Microsoft Word (.docx)</option>
            <option value="odt">LibreOffice (.odt)</option>
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="ods">Calc (.ods)</option>
            <option value="csv">CSV (.csv)</option>
            <option value="epub">eBook (.epub)</option>
            <option value="txt">Texto (.txt)</option>
            <option value="json">JSON (.json)</option>
          </select>
          <label for="convComp">Compresión:</label>
          <select id="convComp">
            <option value="high">Alta calidad</option>
            <option value="balanced">Equilibrada</option>
            <option value="compact">Máxima compresión</option>
          </select>
        </div>
        <div class="row">
          <label class="chk"><input type="checkbox" id="convForceOcr" /> Forzar OCR</label>
          <label class="chk"><input type="checkbox" id="convGray" /> Escala de grises</label>
        </div>
        <button type="button" class="primary" onclick="runConvert()">🚀 Convertir y Descargar</button>
      </div>

      <!-- TAB 2: TRADUCIR DOCUMENTO -->
      <div id="tab1" class="panel col">
        <div class="row">
          <label for="trSrc">Origen:</label>
          <input type="text" id="trSrc" value="auto" style="width:130px;" />
          <label for="trDst">Destino:</label>
          <input type="text" id="trDst" value="Español" style="width:160px;" />
          <label for="trFmt">Formato:</label>
          <select id="trFmt">
            <option value="docx">Word (.docx)</option>
            <option value="odt">LibreOffice (.odt)</option>
            <option value="pdf">PDF</option>
            <option value="pdfa">PDF/A-2b</option>
            <option value="epub">eBook (.epub)</option>
            <option value="txt">Texto (.txt)</option>
          </select>
        </div>
        <div class="row">
          <label class="chk"><input type="checkbox" id="trLayout" checked /> Preservar fondos, colores e imágenes</label>
          <label class="chk"><input type="checkbox" id="trGray" /> Escala de grises</label>
          <label class="chk"><input type="checkbox" id="trHw" /> Letra manuscrita</label>
        </div>
        <button type="button" class="primary" onclick="runTranslateDoc()">🌐 Traducir y Descargar Documento</button>
      </div>

      <!-- TAB 3: IA Y LECTURA FACIL -->
      <div id="tab2" class="panel col">
        <div class="row">
          <label for="aiLang">Idioma respuesta:</label>
          <select id="aiLang">
            <option value="es">Español</option>
            <option value="en">English</option>
            <option value="sv">Svenska</option>
            <option value="fr">Français</option>
            <option value="de">Deutsch</option>
            <option value="pt">Português</option>
            <option value="it">Italiano</option>
          </select>
          <label class="chk"><input type="checkbox" id="aiHw" /> Modo letra manuscrita</label>
        </div>
        <div class="row">
          <button type="button" onclick="runAiSimple('/api/v1/ai/transcribe', 'text')">✍️ Transcribir</button>
          <button type="button" onclick="runAiSimple('/api/v1/ai/summarize', 'summary')">📝 Resumir</button>
          <button type="button" onclick="runAiSimple('/api/v1/ai/easy-read', 'easy_read')">♿ Lectura Fácil (UNE 153101 EX)</button>
          <button type="button" onclick="runAiSimple('/api/v1/ai/anonymize', 'anonymized_text')">🔒 Anonimizar RGPD</button>
        </div>
        <div class="row">
          <input type="text" id="aiQ" placeholder="Pregunta directa sobre el documento..." style="flex:1;min-width:210px;" />
          <button type="button" class="primary" onclick="runAsk(null)">💬 Preguntar</button>
        </div>
        <div class="row">
          <label for="expFmt">Exportar consulta + citas literales:</label>
          <select id="expFmt">
            <option value="docx">Word (.docx)</option>
            <option value="pdf">PDF</option>
            <option value="odt">LibreOffice (.odt)</option>
            <option value="epub">eBook (.epub)</option>
            <option value="md">Markdown (.md)</option>
            <option value="txt">Texto (.txt)</option>
          </select>
          <button type="button" onclick="runAsk(document.getElementById('expFmt').value)">📥 Descargar Informe con Citas</button>
        </div>
        <textarea id="aiOut" class="out" placeholder="Aquí aparecerán las respuestas y el texto extraído..."></textarea>
        <div id="refsArea"></div>
      </div>

      <div id="opStatus" role="status" aria-live="polite"></div>
    </div>
  </div>

<script>
  let curScale = parseFloat(localStorage.getItem("ocr_scale") || "1");
  let curTheme = localStorage.getItem("ocr_theme") || "";
  document.documentElement.style.setProperty("--scale", curScale);
  document.getElementById("zoomLbl").textContent = Math.round(curScale * 100) + "%";
  if (curTheme) document.documentElement.setAttribute("data-theme", curTheme);
  document.getElementById("apiKey").value = localStorage.getItem("ocr_api_key") || "";

  function setZoom(d) {
    curScale = Math.max(0.85, Math.min(1.8, +(curScale + d).toFixed(2)));
    localStorage.setItem("ocr_scale", curScale);
    document.documentElement.style.setProperty("--scale", curScale);
    document.getElementById("zoomLbl").textContent = Math.round(curScale * 100) + "%";
  }
  function resetZoom() { curScale = 1; setZoom(0); }
  function toggleTheme(name) {
    curTheme = (curTheme === name) ? "" : name;
    localStorage.setItem("ocr_theme", curTheme);
    if (curTheme) document.documentElement.setAttribute("data-theme", curTheme);
    else document.documentElement.removeAttribute("data-theme");
  }
  function saveKey() {
    localStorage.setItem("ocr_api_key", document.getElementById("apiKey").value.trim());
    setMsg("Clave API guardada en este navegador.", false);
  }
  function authHeaders() {
    const k = document.getElementById("apiKey").value.trim();
    return k ? { "X-API-Key": k } : {};
  }
  function showTab(n) {
    document.querySelectorAll(".tab-btn").forEach((b, i) => b.setAttribute("aria-selected", i === n ? "true" : "false"));
    document.querySelectorAll(".panel").forEach((p, i) => p.classList.toggle("active", i === n));
  }
  function onFilePicked() {
    const f = document.getElementById("fileInput").files[0];
    document.getElementById("fileName").textContent = f ? ("✓ " + f.name) : "Ningún fichero seleccionado";
  }
  function setMsg(txt, isErr) {
    const el = document.getElementById("opStatus");
    el.className = isErr ? "error" : "status";
    el.textContent = txt;
  }
  function getPickedFile() {
    const f = document.getElementById("fileInput").files[0];
    if (!f) { setMsg("Selecciona primero un fichero o haz una foto arriba.", true); return null; }
    return f;
  }
  async function checkHealth() {
    try {
      const r = await fetch("/api/v1/health", { headers: authHeaders() });
      const data = await r.json();
      const hw = data.hardware ? ` | ${data.hardware.backend.toUpperCase()} (${data.hardware.ai_tier})` : "";
      document.getElementById("healthStatus").textContent = `✓ Servidor v${data.version} activo${hw}`;
    } catch (e) {
      document.getElementById("healthStatus").textContent = "✗ Error conectando: " + e;
    }
  }
  async function downloadBlobResponse(resp, fallbackName) {
    if (!resp.ok) {
      let msg = "HTTP " + resp.status;
      try { const j = await resp.json(); msg = j.detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    const cd = resp.headers.get("Content-Disposition") || "";
    const m = /filename="?([^"]+)"?/i.exec(cd);
    const fname = m ? m[1] : fallbackName;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = fname; document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    return fname;
  }
  async function runConvert() {
    const f = getPickedFile(); if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("format", document.getElementById("convFmt").value);
    fd.append("compression", document.getElementById("convComp").value);
    fd.append("force_ocr", document.getElementById("convForceOcr").checked);
    fd.append("grayscale", document.getElementById("convGray").checked);
    setMsg("⏳ Convirtiendo documento en local...", false);
    try {
      const r = await fetch("/api/v1/convert", { method: "POST", headers: authHeaders(), body: fd });
      const outName = await downloadBlobResponse(r, "documento_ocr." + document.getElementById("convFmt").value);
      setMsg("✓ Descargado: " + outName, false);
    } catch (e) { setMsg("✗ " + e.message, true); }
  }
  async function runTranslateDoc() {
    const f = getPickedFile(); if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("source_lang", document.getElementById("trSrc").value);
    fd.append("target_lang", document.getElementById("trDst").value);
    fd.append("format", document.getElementById("trFmt").value);
    fd.append("preserve_layout", document.getElementById("trLayout").checked);
    fd.append("grayscale", document.getElementById("trGray").checked);
    fd.append("handwriting", document.getElementById("trHw").checked);
    setMsg("⏳ Traduciendo documento completo con IA local...", false);
    try {
      const r = await fetch("/api/v1/ai/translate-document", { method: "POST", headers: authHeaders(), body: fd });
      const outName = await downloadBlobResponse(r, "documento_traducido." + document.getElementById("trFmt").value);
      setMsg("✓ Traducción descargada: " + outName, false);
    } catch (e) { setMsg("✗ " + e.message, true); }
  }
  async function runAiSimple(endpoint, field) {
    const f = getPickedFile(); if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("handwriting", document.getElementById("aiHw").checked);
    fd.append("lang", document.getElementById("aiLang").value);
    setMsg("⏳ Analizando documento con IA local...", false);
    document.getElementById("refsArea").innerHTML = "";
    try {
      const r = await fetch(endpoint, { method: "POST", headers: authHeaders(), body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      document.getElementById("aiOut").value = j[field] || "";
      setMsg("✓ Análisis completado.", false);
    } catch (e) { setMsg("✗ " + e.message, true); }
  }
  async function runAsk(exportFmt) {
    const f = getPickedFile(); if (!f) return;
    const q = document.getElementById("aiQ").value.trim();
    if (!q) { setMsg("Escribe una pregunta primero.", true); return; }
    const fd = new FormData();
    fd.append("file", f);
    fd.append("question", q);
    fd.append("handwriting", document.getElementById("aiHw").checked);
    fd.append("lang", document.getElementById("aiLang").value);
    if (exportFmt) fd.append("export_format", exportFmt);
    setMsg("⏳ Buscando citas literales y generando respuesta...", false);
    try {
      const r = await fetch("/api/v1/ai/ask", { method: "POST", headers: authHeaders(), body: fd });
      if (exportFmt) {
        const outName = await downloadBlobResponse(r, "consulta_citas." + exportFmt);
        setMsg("✓ Informe exportado: " + outName, false);
        return;
      }
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      document.getElementById("aiOut").value = j.answer || "";
      const area = document.getElementById("refsArea");
      area.innerHTML = "";
      (j.references || []).forEach(ref => {
        const d = document.createElement("div");
        d.className = "ref-card";
        const strong = document.createElement("strong");
        strong.textContent = `[${ref.doc_id} / ${ref.ref_id}] ${ref.file_name} — ${ref.section_path}`;
        const p = document.createElement("div");
        p.textContent = "«" + (ref.literal_text || "") + "»";
        d.appendChild(strong); d.appendChild(p); area.appendChild(d);
      });
      setMsg(`✓ Respuesta lista con ${(j.references || []).length} cita(s) literal(es).`, false);
    } catch (e) { setMsg("✗ " + e.message, true); }
  }
  function speakOut() {
    if (!("speechSynthesis" in window)) { setMsg("Tu navegador no soporta lectura por voz.", true); return; }
    window.speechSynthesis.cancel();
    const txt = document.getElementById("aiOut").value.trim() || document.getElementById("opStatus").textContent;
    if (!txt) return;
    const u = new SpeechSynthesisUtterance(txt);
    window.speechSynthesis.speak(u);
  }
  function stopSpeak() { if ("speechSynthesis" in window) window.speechSynthesis.cancel(); }
</script>
</body>
</html>
"""
