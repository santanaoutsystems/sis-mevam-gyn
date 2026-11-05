/* Tabelas com filtro e ordenação pelos cabeçalhos: posiciona o menu aberto, procura valores
   e, nos relatórios, imprime direto (?imprimir=1) e registra a impressão na Auditoria. */
(function () {
  function fecharOutros(atual) {
    document.querySelectorAll("details.menu-col[open]").forEach(function (d) { if (d !== atual) d.open = false; });
  }
  function posicionar(d) {
    var painel = d.querySelector(".menu-col-painel");
    if (!painel) return;
    var r = d.getBoundingClientRect(), largura = painel.offsetWidth || 330;
    var esquerda = Math.min(Math.max(8, r.left), window.innerWidth - largura - 8);
    painel.style.left = esquerda + "px";
    var abaixo = window.innerHeight - r.bottom - 12, acima = r.top - 12;
    if (abaixo >= 260 || abaixo >= acima) {
      painel.style.top = (r.bottom + 4) + "px"; painel.style.bottom = "auto";
      painel.style.maxHeight = Math.max(abaixo, 160) + "px";
    } else {  // pouco espaço embaixo: abre para cima
      painel.style.top = "auto"; painel.style.bottom = (window.innerHeight - r.top + 4) + "px";
      painel.style.maxHeight = acima + "px";
    }
  }
  document.querySelectorAll("details.menu-col").forEach(function (d) {
    d.addEventListener("toggle", function () { if (d.open) { fecharOutros(d); posicionar(d); } });
  });
  window.addEventListener("scroll", function () { fecharOutros(null); }, { passive: true });
  window.addEventListener("resize", function () { fecharOutros(null); });
  document.addEventListener("click", function (e) {
    if (!e.target.closest("details.menu-col")) fecharOutros(null);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") document.querySelectorAll("details.menu-col[open]").forEach(function (d) {
      d.open = false; var s = d.querySelector("summary"); if (s) s.focus();
    });
  });
  document.querySelectorAll(".busca-opcoes").forEach(function (campo) {
    campo.addEventListener("input", function () {
      var termo = campo.value.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
      campo.closest("form").querySelectorAll(".lista-opcoes label").forEach(function (l) {
        var t = l.textContent.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
        l.style.display = t.indexOf(termo) >= 0 ? "" : "none";
      });
    });
  });
  // Catálogo: aberto no PC (lateral), recolhido no celular
  var cat = document.querySelector("details.catalogo");
  if (cat && !window.matchMedia("(min-width: 1000px)").matches) cat.open = false;
  // Relatórios: registro da impressão e impressão automática
  var rel = document.querySelector("[data-relatorio]");
  if (rel) {
    var avisado = false;
    window.addEventListener("beforeprint", function () {
      if (avisado) return; avisado = true;
      var dados = new FormData();
      dados.append("csrf", rel.getAttribute("data-csrf"));
      dados.append("relatorio", rel.getAttribute("data-relatorio"));
      dados.append("filtros", rel.getAttribute("data-filtros") || "");
      dados.append("linhas", rel.getAttribute("data-linhas") || "0");
      try { navigator.sendBeacon ? navigator.sendBeacon("/relatorios/impressao", dados)
        : fetch("/relatorios/impressao", { method: "POST", body: dados, credentials: "same-origin" }); } catch (e) {}
    });
    if (/[?&]imprimir=1/.test(location.search)) setTimeout(function () { window.print(); }, 400);
  }
  document.querySelectorAll("[data-imprimir]").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });
})();
