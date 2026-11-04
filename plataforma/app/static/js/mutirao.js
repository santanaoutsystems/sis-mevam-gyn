/* Mutirão de fichas: lê a foto ou o PDF da ficha (OCR) e preenche os campos para a voluntária conferir. */
(function () {
  "use strict";
  const entrada = document.getElementById("docOcr");
  if (!entrada || typeof OcrEngine === "undefined") return;
  const barra = document.getElementById("ocrBarra"), status = document.getElementById("ocrStatus");
  const CAMPOS = ["nome_completo", "data_nascimento", "cpf", "whatsapp", "email"];
  // As bibliotecas de leitura (vários MB) só são baixadas quando a voluntária escolhe a primeira ficha
  const carregarScript = (src) => new Promise((ok, erro) => {
    if (document.querySelector(`script[src="${src}"]`)) return ok();
    const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = erro;
    document.head.appendChild(s);
  });
  const carregar = async (pdf) => {
    if (typeof Tesseract === "undefined") await carregarScript("https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js");
    if (pdf && !window.pdfjsLib) {
      await carregarScript("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js");
      pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
    }
  };
  const motor = new OcrEngine();
  // Com o Drive ligado, a foto vai junto com a ficha: reduzimos a imagem (cerca de 300 KB) antes do envio
  const paraDrive = entrada.name === "foto_ficha";
  const reduzir = (arq) => new Promise((ok) => {
    if (!arq.type.startsWith("image/")) return ok(arq);
    const img = new Image(), url = URL.createObjectURL(arq);
    img.onload = () => {
      const lado = 1800, k = Math.min(1, lado / Math.max(img.width, img.height));
      const cv = document.createElement("canvas"); cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height); URL.revokeObjectURL(url);
      cv.toBlob((b) => ok(b && b.size < arq.size ? new File([b], arq.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : arq),
                "image/jpeg", 0.82);
    };
    img.onerror = () => { URL.revokeObjectURL(url); ok(arq); };
    img.src = url;
  });
  let trocando = false;
  entrada.addEventListener("change", async () => {
    if (trocando) return;
    const arquivo = entrada.files[0];
    if (!arquivo) return;
    if (paraDrive && window.DataTransfer) {
      const dt = new DataTransfer();
      for (const f of Array.from(entrada.files).slice(0, 3)) dt.items.add(await reduzir(f));
      trocando = true; entrada.files = dt.files; trocando = false;
    }
    const arq = document.getElementById("arquivo");
    if (arq && !arq.value) arq.value = arquivo.name;
    status.textContent = "Preparando a leitura da ficha...";
    try {
      await carregar(arquivo.name.toLowerCase().endsWith(".pdf"));
      const r = await motor.processFile(arquivo, (p, txt) => { barra.style.width = p + "%"; status.textContent = txt; });
      let n = 0;
      for (const campo of CAMPOS) {
        const el = document.getElementById(campo), v = r[campo];
        if (el && v && typeof v === "string" && !el.value) {
          el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); n++;
        }
      }
      const fotos = paraDrive ? ` 📎 ${entrada.files.length} foto(s) prontas para o Drive.` : "";
      status.textContent = (n ? `✅ ${n} campo(s) lidos da ficha. Confira cada um com o papel e corrija o que estiver errado.`
                              : "Não conseguimos ler os campos (letra à mão ou foto escura). Digite os dados.") + fotos;
    } catch (e) {
      status.textContent = "Não foi possível ler este arquivo. Digite os dados." + (paraDrive ? " A foto vai para o Drive mesmo assim." : "");
    }
  });
})();
