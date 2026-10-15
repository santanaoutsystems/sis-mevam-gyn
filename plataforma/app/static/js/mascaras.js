/* Máscaras ativas e preenchimento automático — SIS MEVAM-GYN
 *
 * Use nos inputs:
 *   data-mascara="data"     -> dd/mm/aaaa (teclado numérico; as barras entram sozinhas)
 *   data-mascara="hora"     -> HH:MM
 *   data-mascara="telefone" -> (62) 99999-9999
 *   data-mascara="cep"      -> 00000-000 e busca o endereço (ViaCEP)
 *   data-mascara="moeda"    -> 1.234,56
 */
(function () {
  "use strict";

  const soDigitos = (v) => (v || "").replace(/\D/g, "");

  const formatos = {
    data(v) {
      const d = soDigitos(v).slice(0, 8);
      if (d.length <= 2) return d;
      if (d.length <= 4) return d.slice(0, 2) + "/" + d.slice(2);
      return d.slice(0, 2) + "/" + d.slice(2, 4) + "/" + d.slice(4);
    },
    hora(v) {
      const d = soDigitos(v).slice(0, 4);
      return d.length <= 2 ? d : d.slice(0, 2) + ":" + d.slice(2);
    },
    telefone(v) {
      let d = soDigitos(v);
      if (d.startsWith("55") && d.length > 11) d = d.slice(2);
      d = d.slice(0, 11);
      if (d.length <= 2) return d.length ? "(" + d : "";
      if (d.length <= 6) return "(" + d.slice(0, 2) + ") " + d.slice(2);
      if (d.length <= 10) return "(" + d.slice(0, 2) + ") " + d.slice(2, 6) + "-" + d.slice(6);
      return "(" + d.slice(0, 2) + ") " + d.slice(2, 7) + "-" + d.slice(7);
    },
    cep(v) {
      const d = soDigitos(v).slice(0, 8);
      return d.length <= 5 ? d : d.slice(0, 5) + "-" + d.slice(5);
    },
    moeda(v) {
      const d = soDigitos(v).replace(/^0+/, "");
      if (!d) return "";
      const n = d.padStart(3, "0");
      const inteiro = n.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
      return inteiro + "," + n.slice(-2);
    },
  };

  const teclados = { data: "numeric", hora: "numeric", telefone: "tel", cep: "numeric", moeda: "decimal" };
  const tamanhos = { data: 10, hora: 5, telefone: 15, cep: 9 };
  const exemplos = { data: "dd/mm/aaaa", hora: "HH:MM", telefone: "(62) 99999-9999", cep: "00000-000", moeda: "0,00" };

  function dataValida(texto) {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(texto);
    if (!m) return false;
    const d = +m[1], mes = +m[2], a = +m[3];
    const dt = new Date(a, mes - 1, d);
    return dt.getFullYear() === a && dt.getMonth() === mes - 1 && dt.getDate() === d && a >= 1900;
  }

  function hojeGyn() {
    // Data de hoje no fuso de Goiânia, independente do fuso do aparelho
    const partes = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", year: "numeric" })
      .format(new Date());
    return partes; // dd/mm/aaaa
  }
  window.MevamDatas = { hojeGyn, dataValida };

  function aplicar(el) {
    const tipo = el.dataset.mascara;
    if (!formatos[tipo] || el.dataset.mascaraPronta) return;
    el.dataset.mascaraPronta = "1";
    el.setAttribute("inputmode", teclados[tipo]);
    el.setAttribute("autocomplete", el.getAttribute("autocomplete") || "off");
    if (tamanhos[tipo]) el.setAttribute("maxlength", tamanhos[tipo]);
    if (!el.placeholder) el.placeholder = exemplos[tipo];
    if (el.value) el.value = formatos[tipo](el.value);

    el.addEventListener("input", () => {
      const antes = el.value;
      el.value = formatos[tipo](el.value);
      if (antes !== el.value) el.setSelectionRange(el.value.length, el.value.length);
      el.setCustomValidity("");
      if (tipo === "data" && el.value.length === 10 && !dataValida(el.value)) {
        el.setCustomValidity("Data inválida");
      }
      if (tipo === "cep" && soDigitos(el.value).length === 8) buscarCep(el);
    });
    el.addEventListener("blur", () => {
      if (tipo === "data" && el.value && !dataValida(el.value)) {
        el.setCustomValidity("Data inválida. Use dd/mm/aaaa.");
        el.reportValidity();
      }
    });

    // Atalho: tecla "h" num campo de data preenche com hoje
    if (tipo === "data") {
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "h" || ev.key === "H") { ev.preventDefault(); el.value = hojeGyn(); el.dispatchEvent(new Event("input")); }
      });
    }
  }

  let ultimoCep = "";
  async function buscarCep(el) {
    const cep = soDigitos(el.value);
    if (cep === ultimoCep) return;
    ultimoCep = cep;
    const form = el.form || document;
    const campo = (n) => form.querySelector(`[name="${n}"]`);
    try {
      const r = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
      const d = await r.json();
      if (d.erro) return;
      const preencher = (nome, valor) => { const c = campo(nome); if (c && valor && !c.value) { c.value = valor; c.dispatchEvent(new Event("input")); } };
      preencher("endereco", d.logradouro);
      preencher("bairro", d.bairro);
      preencher("cidade", d.localidade ? `${d.localidade} - ${d.uf}` : "");
      const end = campo("endereco");
      if (end) end.focus();
    } catch (e) { /* sem internet: segue manual */ }
  }

  function iniciar(raiz) {
    (raiz || document).querySelectorAll("[data-mascara]").forEach(aplicar);
  }
  window.MevamMascaras = { iniciar, formatos, soDigitos };
  document.addEventListener("DOMContentLoaded", () => iniciar(document));
})();
