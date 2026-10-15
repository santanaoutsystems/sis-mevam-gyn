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
