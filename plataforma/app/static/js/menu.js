/* Menu lateral: grupos que abrem e fecham, painel flutuante no PC, gaveta no celular,
   "Letras maiores" e confirmação ao sair. Sem dependências. */
(function () {
  var menu = document.getElementById("menu");
  if (!menu) return;
  var raiz = document.documentElement;
  var scrim = document.querySelector(".menu-scrim");
  var abrir = document.querySelector(".abrir-menu");
  var celular = window.matchMedia("(max-width: 899px)");
  var comMouse = window.matchMedia("(hover: hover) and (min-width: 900px)");

  function ler(chave, padrao) { try { return JSON.parse(localStorage.getItem(chave)) || padrao; } catch (e) { return padrao; } }
  function gravar(chave, valor) { try { localStorage.setItem(chave, JSON.stringify(valor)); } catch (e) {} }

  /* ---------- Grupos: a escolha de cada grupo fica guardada no aparelho ---------- */
  var prefs = ler("menu-grupos", {});
  function marcarGrupo(g, aberto) {
    g.classList.toggle("aberto", aberto);
    g.classList.remove("flutuante");
    var b = g.querySelector(":scope > .grupo");
    if (b) b.setAttribute("aria-expanded", aberto ? "true" : "false");
  }
  menu.querySelectorAll(".menu-grupo").forEach(function (g) {
    var chave = g.dataset.grupo;
    if (g.hasAttribute("data-tem-ativo")) marcarGrupo(g, true);       /* o grupo da tela atual sempre abre */
    else if (prefs[chave] !== undefined) marcarGrupo(g, !!prefs[chave]);

    g.querySelector(":scope > .grupo").addEventListener("click", function () {
      var aberto = !g.classList.contains("aberto");
      marcarGrupo(g, aberto);
      prefs[chave] = aberto;
      gravar("menu-grupos", prefs);
    });

    /* PC com mouse: grupo fechado mostra as sub-tarefas num painel ao lado */
    g.addEventListener("mouseenter", function () {
      if (!comMouse.matches || g.classList.contains("aberto")) return;
      var sub = g.querySelector(":scope > .menu-sub");
      var topo = g.getBoundingClientRect().top;
      g.classList.add("flutuante");
      var altura = sub.offsetHeight;
      var max = window.innerHeight - altura - 8;
      g.style.setProperty("--flutuante-topo", Math.max(8, Math.min(topo, max)) + "px");
    });
    g.addEventListener("mouseleave", function () { g.classList.remove("flutuante"); });
  });

  /* ---------- Gaveta do celular ---------- */
  function ajustarAcessibilidade() {
    var escondido = celular.matches && !menu.classList.contains("aberto");
    if (escondido) { menu.setAttribute("aria-hidden", "true"); menu.inert = true; }
    else { menu.removeAttribute("aria-hidden"); menu.inert = false; }
  }
  function abrirGaveta() {
    menu.classList.add("aberto");
    if (scrim) scrim.hidden = false;
    if (abrir) abrir.setAttribute("aria-expanded", "true");
    ajustarAcessibilidade();
    var foco = menu.querySelector(".ativo") || menu.querySelector(".menu-fechar");
    if (foco) foco.focus({ preventScroll: false });
  }
  function fecharGaveta(devolverFoco) {
    if (!menu.classList.contains("aberto")) return;
    menu.classList.remove("aberto");
    if (scrim) scrim.hidden = true;
    if (abrir) abrir.setAttribute("aria-expanded", "false");
    ajustarAcessibilidade();
    if (devolverFoco && abrir) abrir.focus();
  }
  if (abrir) abrir.addEventListener("click", function () {
    if (menu.classList.contains("aberto")) fecharGaveta(true); else abrirGaveta();
  });
  document.querySelectorAll("[data-menu-fechar]").forEach(function (el) {
    el.addEventListener("click", function () { fecharGaveta(true); });
  });
  menu.addEventListener("click", function (ev) {
    if (ev.target.closest("a[href]")) fecharGaveta(false);   /* escolheu uma tela */
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    menu.querySelectorAll(".menu-grupo.flutuante").forEach(function (g) { g.classList.remove("flutuante"); });
    fecharGaveta(true);
  });
  var mudou = function () {
    if (!celular.matches) { menu.classList.remove("aberto"); if (scrim) scrim.hidden = true; }
    ajustarAcessibilidade();
  };
  if (celular.addEventListener) celular.addEventListener("change", mudou); else celular.addListener(mudou);
  ajustarAcessibilidade();

  /* ---------- Letras maiores (guardado no aparelho) ---------- */
  function pintarLetras() {
    var maior = raiz.dataset.letras === "maior";
    document.querySelectorAll(".botao-letras").forEach(function (b) {
      b.setAttribute("aria-pressed", maior ? "true" : "false");
      var t = b.querySelector(".txt");
      if (t) t.textContent = maior ? "Letras normais" : "Letras maiores";
    });
  }
  document.querySelectorAll(".botao-letras").forEach(function (b) {
    b.addEventListener("click", function () {
      var maior = raiz.dataset.letras !== "maior";
      if (maior) raiz.dataset.letras = "maior"; else delete raiz.dataset.letras;
      try { localStorage.setItem("letras", maior ? "maior" : "normal"); } catch (e) {}
      pintarLetras();
    });
  });
  pintarLetras();

  /* ---------- Sair: pede confirmação ---------- */
  var dialogo = document.getElementById("dialogo-sair");
  document.querySelectorAll("form[data-confirmar-sair]").forEach(function (form) {
    form.addEventListener("submit", function (ev) {
      if (!dialogo || typeof dialogo.showModal !== "function" || form.dataset.confirmado) return;
      ev.preventDefault();
      dialogo.showModal();
      dialogo.querySelector("[data-cancelar]").onclick = function () { dialogo.close(); };
      dialogo.querySelector("[data-sair]").onclick = function () {
        form.dataset.confirmado = "1";
        dialogo.close();
        form.submit();
      };
    });
  });
})();
