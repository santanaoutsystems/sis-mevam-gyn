import fs from "fs";
/* Confere o contraste (WCAG AA) de todo texto visível, nos temas claro e escuro.
   Uso: BASE=http://localhost:8000 node scripts/verificar_contraste.mjs  (banco de demonstração; precisa do pacote playwright) */
import { chromium } from "playwright";
const B = process.env.BASE || "http://127.0.0.1:8000";
const SENHA = process.env.SENHA || "Demo1234";
const CREDOS = process.env.CREDOS ? fs.readFileSync(process.env.CREDOS, "utf8").trim().split("\n") : [];
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const res = [];
async function auditar(page, nome, tema) {
  await page.evaluate(t => { document.documentElement.dataset.tema = t; }, tema);
  await page.waitForTimeout(150);
  const falhas = await page.evaluate(() => {
    function rgba(s) { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    function lum([r, g, b]) { const f = c => { c /= 255; return c <= .03928 ? c / 12.92 : Math.pow((c + .055) / 1.055, 2.4); }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); }
    function mix(top, bot) { const a = top[3]; return [top[0]*a+bot[0]*(1-a), top[1]*a+bot[1]*(1-a), top[2]*a+bot[2]*(1-a), 1]; }
    function fundo(el) {
      const camadas = [];
      for (let e = el; e; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (cs.backgroundImage && cs.backgroundImage !== "none") {
          // gradiente: pega a primeira cor do gradiente como aproximação
          const m = cs.backgroundImage.match(/rgba?\([^)]+\)/g);
          if (m) { const cores = m.map(rgba); camadas.push({grad: cores}); if (cores.every(c => c[3] >= 1)) break; }
        }
        const c = rgba(cs.backgroundColor); if (c && c[3] > 0) { camadas.push({cor: c}); if (c[3] >= 1) break; }
      }
      let base = [255, 255, 255, 1];
      const opcoes = [];
      // resolve do fundo para o topo; para gradiente devolve várias opções
      let bases = [base];
      for (let i = camadas.length - 1; i >= 0; i--) {
        const k = camadas[i];
        if (k.cor) bases = bases.map(b => mix(k.cor, b));
        else bases = k.grad.flatMap(g => bases.map(b => mix(g, b)));
      }
      return bases;
    }
    const out = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const vistos = new Set();
    while (walker.nextNode()) {
      const n = walker.currentNode; if (!n.textContent.trim()) continue;
      const el = n.parentElement; if (vistos.has(el)) continue; vistos.add(el);
      const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
      const cs = getComputedStyle(el); if (cs.visibility === "hidden" || +cs.opacity === 0) continue;
      if (el.closest(".papel") ) continue;
      if (/\p{Extended_Pictographic}/u.test(n.textContent.trim()) && n.textContent.trim().length <= 3) continue;
      let cor = rgba(cs.color); let op = 1; for (let e = el; e; e = e.parentElement) op *= +getComputedStyle(e).opacity;
      const bgs = fundo(el);
      const tam = parseFloat(cs.fontSize), peso = +cs.fontWeight;
      const grande = tam >= 24 || (tam >= 18.66 && peso >= 700);
      const minimo = grande ? 3 : 4.5;
      let pior = 99;
      for (const bg of bgs) {
        const c = mix([cor[0], cor[1], cor[2], cor[3] * op], bg);
        const L1 = lum(c), L2 = lum(bg); const ratio = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
        pior = Math.min(pior, ratio);
      }
      if (pior < minimo) out.push({ texto: n.textContent.trim().slice(0, 40), tag: el.tagName + (el.className ? "." + String(el.className).split(" ").join(".") : ""), cor: cs.color, ratio: +pior.toFixed(2), minimo });
    }
    return out;
  });
  for (const f of falhas) res.push({ pagina: nome, tema, ...f });
  return falhas.length;
}
async function sessao(email) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const p = await ctx.newPage();
  if (email) { await p.goto(B + "/entrar"); await p.fill("#email", email); await p.fill("#senha", SENHA); await Promise.all([p.waitForNavigation(), p.click("button[type=submit]")]); }
  return p;
}
const paginas = { anon: ["/entrar", "/ficha", "/privacidade", ...CREDOS],
  admin: ["/inicio", "/agenda", "/agenda?visao=calendario", "/membros", "/membros/1", "/eventos/1", "/eventos/novo", "/eventos/1/relatorio", "/eventos/1/relatorio?tipo=financeiro", "/eventos/1/relatorio?tipo=inadimplentes", "/relatorios/periodo", "/admin/usuarios", "/admin/setores", "/admin/auditoria", "/minha-ficha", "/trocar-senha"],
  membro: ["/inicio", "/agenda", "/eventos/1", "/minha-ficha"] };
const total = {};
for (const [quem, lista] of Object.entries(paginas)) {
  const p = await sessao(quem === "anon" ? null : quem + "@demo.local");
  if (quem === "admin") {
    await p.goto(B + "/membros/1");
    const link = await p.evaluate(() => { const a = [...document.querySelectorAll("a")].find(a => a.href.includes("/credo/")); return a && a.href; });
    if (link) lista.push(new URL(link).pathname + new URL(link).search);
  }
  for (const url of lista) {
    const r = await p.goto(B + url);
    for (const tema of ["claro", "escuro"]) total[`${quem} ${url} ${tema}`] = `${r.status()} falhas=${await auditar(p, quem + " " + url, tema)}`;
  }
}
console.log(JSON.stringify(total, null, 1));
console.log(JSON.stringify(res, null, 1));
await browser.close();
