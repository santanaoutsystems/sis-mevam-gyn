/* Alterna tema claro/escuro. A escolha fica no aparelho (localStorage); sem escolha, segue o sistema. */
(function () {
  var raiz = document.documentElement;
  function atual() {
    if (raiz.dataset.tema) return raiz.dataset.tema;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro";
  }
  function pintar() {
    var t = atual();
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", t === "escuro" ? "#0b1220" : "#1e3a8a");
    document.querySelectorAll(".botao-tema").forEach(function (b) {
      b.textContent = t === "escuro" ? "☀️" : "🌙";
      b.setAttribute("aria-label", t === "escuro" ? "Usar tema claro (dia)" : "Usar tema escuro (noite)");
      b.title = b.getAttribute("aria-label");
    });
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest && ev.target.closest(".botao-tema");
    if (!b) return;
    var novo = atual() === "escuro" ? "claro" : "escuro";
    raiz.dataset.tema = novo;
    try { localStorage.setItem("tema", novo); } catch (e) {}
    pintar();
  });
  if (window.matchMedia) {
    var mq = matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", pintar);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", pintar); else pintar();
})();

/* Mostrar/ocultar senha: acrescenta um botão de olho em todo campo de senha. */
(function () {
  var OLHO = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
  var FECHADO = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M3 3l18 18M10.6 5.1A10.4 10.4 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
  function marcar(botao, campo) {
    var visivel = campo.type === "text";
    botao.innerHTML = visivel ? FECHADO : OLHO;
    botao.setAttribute("aria-pressed", visivel ? "true" : "false");
    botao.setAttribute("aria-label", visivel ? "Ocultar senha" : "Mostrar senha");
    botao.title = botao.getAttribute("aria-label");
  }
  function preparar() {
    document.querySelectorAll('input[type="password"]').forEach(function (campo) {
      if (campo.dataset.olho) return;
      campo.dataset.olho = "1";
      var caixa = document.createElement("span");
      caixa.className = "campo-senha";
      campo.parentNode.insertBefore(caixa, campo);
      caixa.appendChild(campo);
      var botao = document.createElement("button");
      botao.type = "button";
      botao.className = "ver-senha";
      if (campo.id) botao.setAttribute("aria-controls", campo.id);
      marcar(botao, campo);
      botao.addEventListener("click", function () {
        var fim = campo.selectionEnd;
        campo.type = campo.type === "password" ? "text" : "password";
        marcar(botao, campo);
        campo.focus();
        try { campo.setSelectionRange(fim, fim); } catch (e) {}
      });
      caixa.appendChild(botao);
      /* Ao enviar, volta a ocultar para o navegador não guardar a senha como texto comum. */
      if (campo.form) campo.form.addEventListener("submit", function () { campo.type = "password"; });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", preparar); else preparar();
})();
