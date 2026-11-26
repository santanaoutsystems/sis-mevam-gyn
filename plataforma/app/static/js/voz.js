/* Preenchimento por voz (pt-BR) — usa o reconhecimento de fala do próprio navegador
 * (Google no Chrome/Android, Apple no Safari/iPhone).
 *
 * Todo campo de texto, e-mail, telefone, busca e toda <textarea> ganham um botão 🎤
 * ao lado. Para tirar de um campo (ou de um bloco inteiro), use data-sem-voz.
 *
 * Para chegar o mais perto possível do que foi falado:
 *   - pede até 5 interpretações ao navegador e fica com a primeira que faz
 *     sentido para o campo (CPF com dígitos certos, data que existe, e-mail válido);
 *   - entende números por extenso ("sessenta e dois", "mil novecentos e setenta",
 *     "meia" = 6 em telefone/CPF), datas ("doze de março de 1970"), horas
 *     ("sete e meia da noite"), valores ("cinquenta reais e vinte centavos")
 *     e e-mail ("maria ponto souza arroba gmail ponto com");
 *   - nomes ganham iniciais maiúsculas (de, da, dos ficam minúsculos);
 *   - em textos longos é um ditado: continua ouvindo até tocar de novo no 🎤,
 *     e entende "vírgula", "ponto final", "ponto de interrogação", "nova linha".
 *
 * O tipo do campo vem de data-voz="..." ou é deduzido da máscara / do tipo do input:
 *   nome, data, diames, hora, telefone, cep, cpf, moeda, email, numero, codigo,
 *   arquivo, texto (ditado longo), frase (uma linha).
 */
(function () {
  "use strict";

  const MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                 "setembro", "outubro", "novembro", "dezembro"];
  const VALORES = {
    zero: 0, um: 1, uma: 1, primeiro: 1, dois: 2, duas: 2, tres: 3, quatro: 4, cinco: 5,
    seis: 6, sete: 7, oito: 8, nove: 9, dez: 10, onze: 11, doze: 12, treze: 13,
    quatorze: 14, catorze: 14, quinze: 15, dezesseis: 16, dezasseis: 16, dezessete: 17,
    dezassete: 17, dezoito: 18, dezenove: 19, dezanove: 19, vinte: 20, trinta: 30,
    quarenta: 40, cinquenta: 50, sessenta: 60, setenta: 70, oitenta: 80, noventa: 90,
    cem: 100, cento: 100, duzentos: 200, duzentas: 200, trezentos: 300, trezentas: 300,
    quatrocentos: 400, quatrocentas: 400, quinhentos: 500, quinhentas: 500,
    seiscentos: 600, seiscentas: 600, setecentos: 700, setecentas: 700,
    oitocentos: 800, oitocentas: 800, novecentos: 900, novecentas: 900,
  };
  const PARTICULAS = new Set(["de", "da", "do", "das", "dos", "e", "di", "du", "del", "van", "von"]);

  const semAcento = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "");
  const soDigitos = (t) => (t || "").replace(/\D/g, "");
  const dois = (n) => String(n).padStart(2, "0");

  /* Separa as palavras e junta os números falados em grupos:
   * "sessenta e dois nove nove" -> [62, 9, 9]; "mil novecentos e setenta" -> [1970].
   * Dígitos já escritos ("1970", "62") viram grupos próprios (como texto, para manter zeros). */
  function gruposNumericos(texto, meiaSeis) {
    const palavras = semAcento(texto.toLowerCase()).replace(/(\d)\s*[º°ª]/g, "$1")
      .replace(/[^a-z0-9]+/g, " ").trim().split(" ").filter(Boolean);
    const grupos = [];
    let atual = null; // {total, ultimo, mil}
    let ligou = false;
    const fechar = () => { if (atual) grupos.push(String(atual.total + atual.mil)); atual = null; };
    for (const p of palavras) {
      if (/^\d+$/.test(p)) { fechar(); grupos.push(p); ligou = false; continue; }
      if (p === "e") { ligou = !!atual; continue; }
      if (p === "mil") {
        if (!atual) atual = { total: 1, ultimo: 1, mil: 0 };
        atual.mil = (atual.total || 1) * 1000; atual.total = 0; atual.ultimo = 1000; ligou = false;
        continue;
      }
      let v = VALORES[p];
      if (v === undefined && meiaSeis && p === "meia") v = 6;
      if (v === undefined) { fechar(); ligou = false; continue; }
      // Junta "sessenta e dois", "cento e vinte", "mil novecentos": cada parte menor que a anterior
      const cabe = atual && (atual.ultimo === 1000 && v < 1000
        || atual.ultimo >= 100 && atual.ultimo < 1000 && v < 100
        || ligou && atual.ultimo >= 20 && atual.ultimo < 100 && atual.ultimo % 10 === 0 && v < 10);
      if (cabe) { atual.total += v; atual.ultimo = v; }
      else { fechar(); atual = { total: v, ultimo: v, mil: 0 }; }
      ligou = false;
    }
    fechar();
    return grupos;
  }

  const numeroFalado = (texto) => gruposNumericos(texto, false).join("");
  const digitosFalados = (texto) => gruposNumericos(texto, true).join("");

  function cpfValido(d) {
    if (d.length !== 11 || /^(\d)\1{10}$/.test(d)) return false;
    for (const n of [9, 10]) {
      let soma = 0;
      for (let i = 0; i < n; i++) soma += +d[i] * (n + 1 - i);
      if ((soma * 10) % 11 % 10 !== +d[n]) return false;
    }
    return true;
  }

  function anoCompleto(a) {
    let ano = +a;
    if (String(a).length <= 2) {
      const agora = new Date().getFullYear() % 100;
      ano += ano > agora ? 1900 : 2000;
    }
    return ano;
  }

  function dataExiste(d, m, a) {
    const dt = new Date(a, m - 1, d);
    return a >= 1900 && a <= 2100 && dt.getFullYear() === a && dt.getMonth() === m - 1 && dt.getDate() === d;
  }

  /* "doze de março de mil novecentos e setenta", "12 de março de 70", "12/03/1970",
   * "primeiro de janeiro de dois mil e cinco", "12 03 1970" -> dd/mm/aaaa */
  function data(texto, comAno) {
    const t = semAcento(texto.toLowerCase());
    let d, m, a;
    const escrito = /(\d{1,2})\s*[\/.\-]\s*(\d{1,2})(?:\s*[\/.\-]\s*(\d{2,4}))?/.exec(t);
    const idxMes = MESES.findIndex((nome) => new RegExp("\\b" + nome + "\\b").test(t));
    if (escrito) {
      [d, m, a] = [+escrito[1], +escrito[2], escrito[3]];
    } else if (idxMes >= 0) {
      const [antes, depois] = t.split(new RegExp("\\b" + MESES[idxMes] + "\\b"));
      const gd = gruposNumericos(antes, false);
      const ga = gruposNumericos(depois, false);
      d = +gd[gd.length - 1]; m = idxMes + 1;
      if (ga.length) a = ga.join("").length === 4 ? ga.join("") : ga[0];
    } else {
      const g = gruposNumericos(t, false);
      const so = g.join("");
      if (g.length >= 3) [d, m, a] = [+g[0], +g[1], g.slice(2).join("")];
      else if (g.length === 2 && !comAno) [d, m] = [+g[0], +g[1]];
      else if (so.length === 8 || so.length === 6) [d, m, a] = [+so.slice(0, 2), +so.slice(2, 4), so.slice(4)];
      else if (so.length === 4 && !comAno) [d, m] = [+so.slice(0, 2), +so.slice(2)];
    }
    if (!d || !m) return { valor: texto, ok: false };
    if (!comAno) {
      const ok = m >= 1 && m <= 12 && dataExiste(d, m, 2000);
      return { valor: dois(d) + "/" + dois(m), ok };
    }
    if (!a) return { valor: dois(d) + "/" + dois(m) + "/", ok: false };
    const ano = anoCompleto(a);
    return { valor: dois(d) + "/" + dois(m) + "/" + ano, ok: dataExiste(d, m, ano) };
  }

  /* "dezenove horas e trinta", "sete e meia da noite", "meio-dia", "19:30" -> HH:MM */
  function hora(texto) {
    const t = semAcento(texto.toLowerCase());
    if (/meio[\s-]?dia/.test(t)) return { valor: /meia/.test(t) ? "12:30" : "12:00", ok: true };
    if (/meia[\s-]?noite/.test(t)) return { valor: "00:00", ok: true };
    let h, min = 0;
    const escrito = /(\d{1,2})\s*(?:[:h]|horas?)\s*(\d{1,2})?/.exec(t);
    if (escrito) { h = +escrito[1]; min = +(escrito[2] || 0); }
    else {
      const g = gruposNumericos(t.replace(/\be meia\b/, " 30 "), false);
      if (!g.length) return { valor: texto, ok: false };
      h = +g[0]; min = +(g[1] || 0);
    }
    if (/\be meia\b/.test(t) && !min) min = 30;
    if (/(da|de) (tarde|noite)/.test(t) && h < 12) h += 12;
    const ok = h >= 0 && h < 24 && min >= 0 && min < 60;
    return { valor: dois(h) + ":" + dois(min), ok };
  }

  /* "cinquenta reais e vinte centavos", "R$ 1.200,50", "mil e duzentos" -> 1.200,50 (a máscara formata) */
  function moeda(texto) {
    const t = semAcento(texto.toLowerCase()).replace(/r\$/g, " ");
    const escrito = /(\d[\d.]*)(?:,(\d{1,2}))?/.exec(t);
    let reais, centavos = 0;
    if (escrito && !/real|reais|centavo/.test(t.replace(escrito[0], ""))) {
      reais = +escrito[1].replace(/\./g, ""); centavos = +((escrito[2] || "0").padEnd(2, "0"));
    } else {
      const [parteReais, parteCent] = t.split(/\breais\b|\breal\b/);
      if (parteCent === undefined && /centavo/.test(t)) { reais = 0; centavos = +numeroFalado(t) || 0; }
      else { reais = +numeroFalado(parteReais) || 0; centavos = +numeroFalado(parteCent || "") || 0; }
    }
    if (reais === undefined || isNaN(reais)) return { valor: texto, ok: false };
    return { valor: reais + "," + dois(centavos), ok: centavos < 100 };
  }

  function telefone(texto) {
    let d = digitosFalados(texto);
    if (d.startsWith("55") && d.length >= 12) d = d.slice(2);
    if (d.startsWith("0") && d.length >= 11) d = d.slice(1);
    if (d.length === 9 && d.startsWith("9")) d = "62" + d; // sem DDD: Goiânia
    return { valor: d, ok: d.length === 11 };
  }

  function cpf(texto) { const d = digitosFalados(texto); return { valor: d, ok: cpfValido(d) }; }
  function cep(texto) { const d = digitosFalados(texto); return { valor: d, ok: d.length === 8 }; }
  function numero(texto) { const d = numeroFalado(texto); return { valor: d, ok: d.length > 0 }; }

  function email(texto) {
    let t = " " + semAcento(texto.toLowerCase()) + " ";
    t = t.replace(/\s(arroba|@)\s?/g, "@")
      .replace(/\s?\bponto com ponto br\b/g, ".com.br").replace(/\s?\bponto com\b/g, ".com")
      .replace(/\s?\bponto\b\s?/g, ".")
      .replace(/\s?\b(underline|underscore|sublinhado|under)\b\s?/g, "_")
      .replace(/\s?\b(traco|hifen|menos)\b\s?/g, "-");
    const ehNumero = (p) => p === "mil" || VALORES[p] !== undefined;
    t = t.replace(/\b[a-z]+(?:\s+[a-z]+)*\b/g, (trecho) => {
      // troca só as sequências de números por extenso: "pedro dois mil" -> "pedro 2000"
      const p = trecho.split(" "), saida = [];
      for (let i = 0; i < p.length;) {
        if (!ehNumero(p[i])) { saida.push(p[i++]); continue; }
        let k = i + 1;
        while (k < p.length && (ehNumero(p[k]) || (p[k] === "e" && ehNumero(p[k + 1] || "")))) k++;
        saida.push(numeroFalado(p.slice(i, k).join(" "))); i = k;
      }
      return saida.join(" ");
    });
    t = t.replace(/\s+/g, "").replace(/\.{2,}/g, ".").replace(/[^a-z0-9@._+\-]/g, "");
    return { valor: t, ok: /^[a-z0-9._+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)+$/.test(t) };
  }

  function nome(texto) {
    const valor = texto.replace(/[.,;!?]+$/g, "").replace(/\s+/g, " ").trim().toLowerCase()
      .split(" ").map((p, i) => (i > 0 && PARTICULAS.has(p)) ? p
        : p.split("-").map((s) => s.charAt(0).toUpperCase() + s.slice(1)).join("-")).join(" ");
    return { valor, ok: /\p{L}/u.test(valor) };
  }

  const UFS = new Set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" "));
  /* "goiânia goiás" / "goiânia go" -> "Goiânia - GO" */
  function cidade(texto) {
    let t = texto.replace(/\s+(estado de|de)\s+goi[aá]s$/i, " GO").replace(/\s+goi[aá]s$/i, " GO");
    const m = /^(.*?)[\s\-\/]+([a-z]{2})$/i.exec(t.trim());
    if (m && UFS.has(m[2].toUpperCase())) return { valor: nome(m[1]).valor + " - " + m[2].toUpperCase(), ok: true };
    return nome(t);
  }

  function codigo(texto) {
    const v = semAcento(texto).toUpperCase().replace(/[^A-Z0-9]/g, "");
    return { valor: v, ok: v.length > 0 };
  }

  function arquivo(texto) {
    const t = texto.replace(/\s+ponto\s+(pdf|jpg|jpeg|png)\b/i, ".$1").replace(/\s+\.\s*/g, ".");
    const m = /^(.*?)(\.(pdf|jpe?g|png))?$/i.exec(t.trim());
    return { valor: nome(m[1]).valor + (m[2] || "").toLowerCase(), ok: true };
  }

  /* Ditado: pontuação falada e primeira letra maiúscula */
  function texto(t) {
    let v = " " + t.trim() + " ";
    const trocas = [
      [/\s+ponto de interroga[cç][aã]o\s*/gi, "? "], [/\s+ponto de exclama[cç][aã]o\s*/gi, "! "],
      [/\s+ponto e v[ií]rgula\s*/gi, "; "], [/\s+dois pontos\s*/gi, ": "],
      [/\s+ponto final\s*/gi, ". "], [/\s+v[ií]rgula\s*/gi, ", "],
      [/\s*\b(nova linha|pr[oó]xima linha)\b\s*/gi, "\n"], [/\s*\bnovo par[aá]grafo\b\s*/gi, "\n\n"],
    ];
    for (const [re, por] of trocas) v = v.replace(re, por);
    v = v.replace(/[ \t]+/g, " ").replace(/ ?\n ?/g, "\n").trim()
      .replace(/(^|[.!?]\s+|\n)(\p{Ll})/gu, (_, a, b) => a + b.toUpperCase());
    return { valor: v, ok: v.length > 0 };
  }

  function frase(t) {
    const v = t.trim();
    return { valor: v.charAt(0).toUpperCase() + v.slice(1), ok: v.length > 0 };
  }

  const NORMALIZAR = {
    nome, cidade, data: (t) => data(t, true), diames: (t) => data(t, false), hora, telefone, cep, cpf,
    moeda, email, numero, codigo, arquivo, texto, frase, busca: (t) => ({ valor: t.trim(), ok: true }),
  };
  const DESCRICAO = {
    data: "Fale a data. Ex.: “doze de março de mil novecentos e setenta”.",
    diames: "Fale o dia e o mês. Ex.: “vinte de outubro”.",
    hora: "Fale a hora. Ex.: “sete e meia da noite”.",
    telefone: "Fale o número com DDD, devagar.",
    cpf: "Fale os 11 números do CPF, devagar.",
    cep: "Fale os 8 números do CEP.",
    moeda: "Fale o valor. Ex.: “cinquenta reais”.",
    email: "Soletre se precisar. Ex.: “maria ponto souza arroba gmail ponto com”.",
    texto: "Pode falar à vontade. Toque no 🎤 de novo para terminar.",
  };

  /* Escolhe, entre as interpretações do navegador, a primeira que é válida para o campo */
  function melhor(alternativas, tipo) {
    const f = NORMALIZAR[tipo] || frase;
    let primeira = null;
    for (const alt of alternativas) {
      const r = f(alt);
      if (!primeira) primeira = r;
      if (r.ok) return r;
    }
    return primeira || { valor: "", ok: false };
  }

  function tipoDoCampo(el) {
    if (el.dataset.voz) return el.dataset.voz;
    const m = el.dataset.mascara;
    if (m && NORMALIZAR[m]) return m;
    if (el.tagName === "TEXTAREA") return "texto";
    if (el.type === "email") return "email";
    if (el.type === "tel") return "telefone";
    if (el.type === "search") return "busca";
    if (el.getAttribute("inputmode") === "numeric") return "numero";
    if (/^(cidade|naturalidade)$/.test(el.name || "")) return "cidade";
    if (/^(nome|conjuge|bairro|voluntaria)/.test(el.name || "") || /\bname\b/.test(el.autocomplete || "")) return "nome";
    return "frase";
  }

  /* ---------- Interface (só no navegador) ---------- */
  const Reconhecimento = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);
  const ERROS = {
    "not-allowed": "O microfone está bloqueado. Toque no cadeado ao lado do endereço do site e permita o microfone.",
    "service-not-allowed": "O microfone está bloqueado. Toque no cadeado ao lado do endereço do site e permita o microfone.",
    "audio-capture": "Não encontrei um microfone neste aparelho.",
    "network": "O reconhecimento de voz precisa de internet. Confira a conexão e tente de novo.",
    "no-speech": "Não ouvi nada. Toque no 🎤 e fale perto do aparelho.",
  };
  const CAMPOS = "input[data-voz], textarea, input[type=text], input[type=email], input[type=tel], input[type=search], input:not([type])";
  let emUso = null; // só um microfone aberto por vez

  function anexarBotao(input) {
    if (input.dataset.vozPronta || input.closest("[data-sem-voz]") || input.disabled || input.readOnly) return;
    if (input.name === "confirmacao" || /username|password/.test(input.autocomplete || "")) return;
    input.dataset.vozPronta = "1";
    const embrulho = document.createElement("div");
    embrulho.className = "com-acao";
    input.parentNode.insertBefore(embrulho, input);
    embrulho.appendChild(input);
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "voz"; btn.textContent = "🎤";
    btn.title = "Preencher por voz"; btn.setAttribute("aria-label", "Preencher por voz");
    embrulho.appendChild(btn);
    const aviso = document.createElement("div");
    aviso.className = "voz-aviso"; aviso.setAttribute("aria-live", "polite"); aviso.hidden = true;
    embrulho.insertAdjacentElement("afterend", aviso);
    const avisar = (msg, erro) => { aviso.textContent = msg || ""; aviso.hidden = !msg; aviso.classList.toggle("erro", !!erro); };

    btn.addEventListener("click", () => {
      if (emUso && emUso.btn === btn) { emUso.parar(); return; }
      if (emUso) emUso.parar();
      const tipo = tipoDoCampo(input);
      const ditado = tipo === "texto";
      let ativo = true, ouviu = false, silencios = 0, rec = null;
      const base = ditado ? input.value.replace(/\s+$/, "") : "";
      let acumulado = "";

      const terminar = () => {
        ativo = false; btn.classList.remove("gravando");
        btn.setAttribute("aria-label", "Preencher por voz");
        if (emUso && emUso.btn === btn) emUso = null;
      };
      const escrever = (valor) => {
        input.value = valor;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      };

      const ouvir = () => {
        rec = new Reconhecimento();
        rec.lang = "pt-BR";
        rec.interimResults = true;
        rec.maxAlternatives = 5;
        rec.continuous = false; // reinicia sozinho no ditado: mais estável no Android
        rec.onresult = (ev) => {
          let parcial = "";
          for (let i = ev.resultIndex; i < ev.results.length; i++) {
            const r = ev.results[i];
            if (!r.isFinal) { parcial += r[0].transcript; continue; }
            ouviu = true; silencios = 0;
            const alternativas = Array.from(r, (a) => a.transcript.trim()).filter(Boolean);
            if (ditado) {
              acumulado = (acumulado + " " + alternativas[0]).trim();
              const v = texto(acumulado).valor;
              escrever(base ? base + (/[.!?]$/.test(base) ? " " : " ") + v : v);
              avisar("🎙 Ouvindo… toque no 🎤 para terminar.");
            } else {
              const r2 = melhor(alternativas, tipo);
              escrever(r2.valor);
              if (r2.ok) avisar("✔ Ouvi: " + input.value + ". Confira antes de salvar.");
              else avisar("Ouvi “" + alternativas[0] + "”. Confira o campo ou toque no 🎤 e fale de novo.", true);
            }
          }
          if (parcial) avisar("🎙 " + parcial + "…");
        };
        rec.onerror = (ev) => {
          if (ev.error === "no-speech" && ditado && ouviu && ++silencios < 2) return; // pausa curta no ditado
          if (ev.error === "aborted") return;
          if (ERROS[ev.error]) avisar(ERROS[ev.error], true);
          if (ev.error !== "no-speech") ativo = false;
          else if (!ditado || silencios >= 2) ativo = false;
        };
        rec.onend = () => {
          if (ativo && ditado) { try { ouvir(); return; } catch (e) { /* segue para terminar */ } }
          if (ditado && ouviu) avisar("✔ Ditado concluído. Confira o texto antes de salvar.");
          terminar();
        };
        rec.start();
      };

      btn.classList.add("gravando");
      btn.setAttribute("aria-label", "Parar de ouvir");
      avisar("🎙 " + (DESCRICAO[tipo] || "Pode falar."));
      emUso = { btn, parar: () => { ativo = false; try { rec && rec.stop(); } catch (e) { terminar(); } } };
      try { ouvir(); } catch (e) { avisar("Não consegui abrir o microfone. Tente de novo.", true); terminar(); }
    });
  }

  function iniciar(raiz) {
    if (!Reconhecimento) return; // navegador sem suporte: nada aparece
    (raiz || document).querySelectorAll(CAMPOS).forEach(anexarBotao);
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { gruposNumericos, melhor, NORMALIZAR };
  }
  if (typeof document !== "undefined") {
    window.MevamVoz = { iniciar, melhor };
    document.addEventListener("DOMContentLoaded", () => {
      iniciar(document);
      // Campos criados depois (ex.: dependentes na ficha) também ganham o 🎤
      if (Reconhecimento && window.MutationObserver) {
        new MutationObserver((mudancas) => mudancas.forEach((m) => m.addedNodes.forEach((n) => {
          if (n.nodeType === 1 && !n.closest(".com-acao")) iniciar(n.parentNode || n);
        }))).observe(document.body, { childList: true, subtree: true });
      }
    });
  }
})();
