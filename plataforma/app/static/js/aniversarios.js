/* Aniversariantes: fecha a janela de aviso, registra o envio por WhatsApp/cópia e monta o link com o texto editado. */
(function () {
  document.querySelectorAll("[data-fechar-janela]").forEach(function (b) {
    b.addEventListener("click", function () { var j = b.closest("[data-janela]"); if (j) j.remove(); });
  });
  var janela = document.querySelector("[data-janela]");
  if (janela) {
    var foco = janela.querySelector("a, button"); if (foco) foco.focus();
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && janela.isConnected) janela.remove(); });
    janela.addEventListener("click", function (e) { if (e.target === janela) janela.remove(); });
  }

  var form = document.querySelector("[data-mensagem]");
  if (!form) return;
  var texto = form.querySelector("textarea[name=texto]");
  function registrar(canal) {
    var dados = new FormData();
    dados.append("csrf", form.querySelector("input[name=csrf]").value);
    dados.append("canal", canal);
    var url = form.getAttribute("data-registrar");
    try { navigator.sendBeacon ? navigator.sendBeacon(url, dados) : fetch(url, { method: "POST", body: dados, credentials: "same-origin" }); } catch (e) {}
    var ok = document.querySelector("[data-enviado]"); if (ok) ok.hidden = false;
  }
  var zap = form.querySelector("[data-whatsapp]");
  if (zap) zap.addEventListener("click", function () {
    zap.href = "https://wa.me/" + zap.getAttribute("data-numero") + "?text=" + encodeURIComponent(texto.value);
    registrar("whatsapp");
  });
  var copiar = form.querySelector("[data-copiar]");
  if (copiar) copiar.addEventListener("click", function () {
    var pronto = function () { copiar.textContent = "✔ Copiado"; registrar("copia"); };
    if (navigator.clipboard) navigator.clipboard.writeText(texto.value).then(pronto, function () { texto.select(); document.execCommand("copy"); pronto(); });
    else { texto.select(); document.execCommand("copy"); pronto(); }
  });
})();
