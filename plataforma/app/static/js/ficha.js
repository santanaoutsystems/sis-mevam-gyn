/* Ficha de Membro em etapas: foto 3x4, filhos, leitura de documento (OCR) e validação. */
(function () {
  "use strict";
  const form = document.getElementById("formFicha");
  if (!form) return;
  const $ = (s, r) => (r || form).querySelector(s);
  const $$ = (s, r) => Array.from((r || form).querySelectorAll(s));

  // ---------------- Etapas ----------------
  const etapas = $$(".etapa");
  const marcadores = $$(".etapas span", document);
  let atual = 0;
  const primeiraComErro = etapas.findIndex((e) => e.querySelector(".campo-erro"));
  if (primeiraComErro >= 0) atual = primeiraComErro;

  function mostrar(i) {
    atual = Math.max(0, Math.min(i, etapas.length - 1));
    etapas.forEach((e, k) => e.classList.toggle("atual", k === atual));
    marcadores.forEach((m, k) => m.classList.toggle("feita", k <= atual));
    const voltar = $("#btnVoltar"), avancar = $("#btnAvancar"), enviar = $("#btnEnviar");
    if (voltar) voltar.style.visibility = atual === 0 ? "hidden" : "visible";
    if (avancar) avancar.style.display = atual === etapas.length - 1 ? "none" : "";
    if (enviar) enviar.style.display = atual === etapas.length - 1 ? "" : "none";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function etapaValida(i) {
    for (const el of etapas[i].querySelectorAll("input, select, textarea")) {
      if (el.offsetParent === null && el.type !== "hidden") continue; // campo oculto por regra
      if (!el.checkValidity()) { el.reportValidity(); return false; }
    }
    return true;
  }

  if (etapas.length > 1) {
    $("#btnAvancar")?.addEventListener("click", () => { if (etapaValida(atual)) mostrar(atual + 1); });
    $("#btnVoltar")?.addEventListener("click", () => mostrar(atual - 1));
    mostrar(atual);
  }

  // ---------------- Campos condicionais ----------------
  function regras() {
    const civil = $("[name=estado_civil]")?.value;
    const casado = civil === "Casado(a)" || civil === "União Estável";
    const conj = $("#grupoConjuge");
    if (conj) { conj.style.display = casado ? "" : "none"; $("[name=conjuge]").required = casado; }
    const bat = $("[name=batizado]:checked")?.value === "Sim";
    const gBat = $("#grupoBatismo");
    if (gBat) { gBat.style.display = bat ? "" : "none"; $("[name=data_batismo]").required = bat; }
    const cong = $("[name=congregava_antes]:checked")?.value === "Sim";
    const gCong = $("#grupoCongregava");
    if (gCong) { gCong.style.display = cong ? "" : "none"; $("[name=onde_congregava]").required = cong; }
  }
  form.addEventListener("change", regras);
  regras();

  // ---------------- Filhos ----------------
  const listaFilhos = $("#filhos");
  const campoFilhos = $("[name=filhos_json]");
  function sincronizarFilhos() {
    const filhos = $$(".filho", listaFilhos).map((l) => ({
      nome: l.querySelector(".f-nome").value.trim(),
      data_nascimento: l.querySelector(".f-nasc").value.trim(),
    })).filter((f) => f.nome);
    campoFilhos.value = JSON.stringify(filhos);
  }
  function adicionarFilho(dados) {
    const linha = document.createElement("div");
    linha.className = "filho";
    linha.innerHTML = `
      <div><label>Nome do filho(a)</label><input type="text" class="f-nome" autocomplete="off"></div>
      <div><label>Nascimento</label><input type="text" class="f-nasc" data-mascara="data"></div>
      <button type="button" class="botao secundario peq" aria-label="Remover">Remover</button>`;
    linha.querySelector(".f-nome").value = (dados && dados.nome) || "";
    linha.querySelector(".f-nasc").value = (dados && dados.data_nascimento) || "";
    linha.querySelector("button").addEventListener("click", () => { linha.remove(); sincronizarFilhos(); });
    linha.addEventListener("input", sincronizarFilhos);
    listaFilhos.appendChild(linha);
    window.MevamMascaras && window.MevamMascaras.iniciar(linha);
  }
  if (listaFilhos && campoFilhos) {
    try { JSON.parse(campoFilhos.value || "[]").forEach(adicionarFilho); } catch (e) { /* ignora */ }
    $("#btnAddFilho")?.addEventListener("click", () => adicionarFilho());
    form.addEventListener("submit", sincronizarFilhos);
  }

  // ---------------- Foto 3x4 (comprimida no aparelho) ----------------
  const campoFoto = $("[name=foto_3x4]");
  const previa = $("#previaFoto");
  function mostrarFoto(url) {
    if (!previa) return;
    previa.innerHTML = url ? `<img src="${url}" alt="Foto 3x4">` : "Sem foto";
  }
  async function processarFoto(arquivo) {
    if (!arquivo) return;
    const url = URL.createObjectURL(arquivo);
    const img = new Image();
    await new Promise((ok, erro) => { img.onload = ok; img.onerror = erro; img.src = url; });
    // Recorte 3x4 centralizado, 480x640
    const alvoW = 480, alvoH = 640, prop = 3 / 4;
    let sw = img.width, sh = img.height, sx = 0, sy = 0;
    if (sw / sh > prop) { sw = sh * prop; sx = (img.width - sw) / 2; } else { sh = sw / prop; sy = (img.height - sh) / 2; }
    const canvas = document.createElement("canvas");
    canvas.width = alvoW; canvas.height = alvoH;
    canvas.getContext("2d").drawImage(img, sx, sy, sw, sh, 0, 0, alvoW, alvoH);
    URL.revokeObjectURL(url);
    const dados = canvas.toDataURL("image/jpeg", 0.82);
    campoFoto.value = dados;
    campoFoto.setCustomValidity("");
    mostrarFoto(dados);
  }
  $$("[data-foto]").forEach((inp) => inp.addEventListener("change", () => processarFoto(inp.files[0])));
  if (campoFoto && campoFoto.value) mostrarFoto(campoFoto.value);
  $("#btnRemoverFoto")?.addEventListener("click", () => { campoFoto.value = ""; mostrarFoto(""); });

  // ---------------- Leitura de documento (OCR) ----------------
  const docInput = $("#docOcr");
  // As bibliotecas de leitura (vários MB) só são baixadas quando alguém escolhe um documento,
  // assim a ficha abre rápido mesmo no 4G.
  const carregarScript = (src) => new Promise((ok, erro) => {
    if (document.querySelector(`script[src="${src}"]`)) return ok();
    const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = erro;
    document.head.appendChild(s);
  });
  const carregarLeitura = async (pdf) => {
    if (typeof Tesseract === "undefined") await carregarScript("https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js");
    if (pdf && !window.pdfjsLib) {
      await carregarScript("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js");
      pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
    }
  };
  if (docInput && typeof OcrEngine !== "undefined") {
    const motor = new OcrEngine();
    const barra = $("#ocrBarra"), status = $("#ocrStatus");
    const mapaSexo = { "Masc.": "Masculino", "Fem.": "Feminino" };
    docInput.addEventListener("change", async () => {
      const arquivo = docInput.files[0];
      if (!arquivo) return;
      status.textContent = "Preparando a leitura do documento...";
      try {
        await carregarLeitura(arquivo.name.toLowerCase().endsWith(".pdf"));
        status.textContent = "Lendo o documento...";
        const r = await motor.processFile(arquivo, (p, txt) => { barra.style.width = p + "%"; status.textContent = txt; });
        let preenchidos = 0;
        for (const [campo, valor] of Object.entries(r)) {
          if (!valor || typeof valor !== "string") continue;
          const v = campo === "sexo" ? (mapaSexo[valor] || valor) : valor;
          const radios = $$(`[name="${campo}"][type=radio]`);
          if (radios.length) {
            const alvo = radios.find((x) => x.value === v);
            if (alvo && !radios.some((x) => x.checked)) { alvo.checked = true; preenchidos++; }
            continue;
          }
          const el = $(`[name="${campo}"]`);
          if (el && !el.value && el.type !== "hidden") {
            el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); preenchidos++;
          }
        }
        $("[name=ocr_documento_nome]").value = arquivo.name;
        regras();
        status.textContent = preenchidos
          ? `✅ ${preenchidos} campo(s) preenchidos a partir do documento. Confira cada um antes de enviar.`
          : "Não encontramos campos legíveis. Preencha manualmente.";
      } catch (e) {
        status.textContent = "Não foi possível ler este arquivo. Preencha manualmente.";
      }
    });
  }

  // Evita envio duplo
  form.addEventListener("submit", (ev) => {
    if (campoFoto && campoFoto.required && !campoFoto.value) {
      ev.preventDefault();
      alert("A foto 3x4 é obrigatória.");
      return;
    }
    const b = $("#btnEnviar");
    if (b) { b.disabled = true; b.textContent = "Enviando..."; }
  });
})();
