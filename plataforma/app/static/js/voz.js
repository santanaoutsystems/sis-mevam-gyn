/* Preenchimento por voz (pt-BR) — usa o reconhecimento de fala do próprio navegador.
 * Coloque data-voz no input: um botão 🎤 aparece ao lado.
 * Campos de data entendem frases como "15 de outubro de 1980".
 */
(function () {
  "use strict";
  const Reconhecimento = window.SpeechRecognition || window.webkitSpeechRecognition;
  const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                 "setembro", "outubro", "novembro", "dezembro"];

  function falaParaData(texto) {
    const t = texto.toLowerCase().replace("marco", "março");
    const m = /(\d{1,2})\s*(?:de\s+)?([a-zç]+|\d{1,2})\s*(?:de\s+)?(\d{4})/.exec(t);
    if (!m) return texto;
    let mes = isNaN(+m[2]) ? MESES.indexOf(m[2]) + 1 : +m[2];
    if (mes < 1) return texto;
    return String(+m[1]).padStart(2, "0") + "/" + String(mes).padStart(2, "0") + "/" + m[3];
  }

  function falaParaEmail(texto) {
    return texto.toLowerCase().replace(/\s+arroba\s+/g, "@").replace(/\s+ponto\s+/g, ".").replace(/\s+/g, "");
  }

  function anexarBotao(input) {
    if (input.dataset.vozPronta) return;
    input.dataset.vozPronta = "1";
    const embrulho = document.createElement("div");
    embrulho.className = "com-acao";
    input.parentNode.insertBefore(embrulho, input);
    embrulho.appendChild(input);
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "voz"; btn.textContent = "🎤";
    btn.title = "Preencher por voz"; btn.setAttribute("aria-label", "Preencher por voz");
    embrulho.appendChild(btn);

    btn.addEventListener("click", () => {
      const rec = new Reconhecimento();
      rec.lang = "pt-BR"; rec.interimResults = false; rec.maxAlternatives = 1;
      btn.classList.add("gravando");
      rec.onresult = (ev) => {
        let texto = ev.results[0][0].transcript.trim();
        const tipo = input.dataset.mascara;
        if (tipo === "data") texto = falaParaData(texto);
        else if (input.type === "email") texto = falaParaEmail(texto);
        else if (tipo === "telefone" || tipo === "cep") texto = texto.replace(/\D/g, "");
        input.value = texto;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      };
      rec.onend = () => btn.classList.remove("gravando");
      rec.onerror = () => btn.classList.remove("gravando");
      rec.start();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!Reconhecimento) return; // navegador sem suporte: nada aparece
    document.querySelectorAll("[data-voz]").forEach(anexarBotao);
  });
})();
