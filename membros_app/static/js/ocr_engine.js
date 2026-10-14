/**
 * OcrEngine - Módulo de Reconhecimento Óptico de Caracteres & Extração Inteligente
 * Suporta PDF (digital ou escaneado via PDF.js), JPG, PNG, WEBP, HEIC e Câmera
 * Integrado com Tesseract.js e expressões regulares treinadas na Ficha MEVAM GYN
 */

class OcrEngine {
  constructor() {
    this.tesseractLoaded = false;
    this.pdfjsLoaded = false;
    this.worker = null;
  }

  async initTesseract() {
    if (this.tesseractLoaded) return;
    if (typeof Tesseract === 'undefined') {
      console.warn("Tesseract.js ainda não carregado.");
      return;
    }
    this.tesseractLoaded = true;
  }

  async processFile(file, progressCallback = null) {
    const fileName = file.name.toLowerCase();
    let extractedText = "";

    if (fileName.endsWith('.pdf')) {
      if (progressCallback) progressCallback(20, "Lendo páginas do arquivo PDF...");
      extractedText = await this.processPdf(file, progressCallback);
    } else {
      if (progressCallback) progressCallback(20, "Otimizando imagem para reconhecimento OCR...");
      extractedText = await this.processImage(file, progressCallback);
    }

    if (progressCallback) progressCallback(90, "Identificando campos cadastrais com IA...");
    const parsedData = this.parseDocumentText(extractedText);
    parsedData.fileName = file.name;
    parsedData.rawText = extractedText;

    if (progressCallback) progressCallback(100, "Concluído!");
    return parsedData;
  }

  async processImage(file, progressCallback) {
    if (typeof Tesseract === 'undefined') {
      throw new Error("Mecanismo Tesseract.js indisponível.");
    }

    const { data: { text } } = await Tesseract.recognize(
      file,
      'por+eng', // Português e Inglês para caracteres acentuados e formatos
      {
        logger: (m) => {
          if (progressCallback && m.status === 'recognizing text') {
            const p = Math.round(20 + (m.progress * 65));
            progressCallback(p, `Reconhecendo caracteres (${Math.round(m.progress * 100)}%)...`);
          }
        }
      }
    );
    return text;
  }

  async processPdf(file, progressCallback) {
    const arrayBuffer = await file.arrayBuffer();
    
    // Tenta primeiro extração direta de texto via PDF.js
    if (typeof pdfjsLib !== 'undefined') {
      try {
        const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        let fullText = "";

        for (let i = 1; i <= pdf.numPages; i++) {
          if (progressCallback) {
            progressCallback(20 + Math.round((i / pdf.numPages) * 30), `Lendo página ${i} de ${pdf.numPages}...`);
          }
          const page = await pdf.getPage(i);
          const textContent = await page.getTextContent();
          const pageText = textContent.items.map(item => item.str).join(" ");
          fullText += pageText + "\n";
        }

        // Se o texto direto tiver bom volume (PDF digital)
        if (fullText.trim().length > 100) {
          return fullText;
        }

        // Se for PDF escaneado (imagem dentro do PDF), renderiza primeira página no canvas e roda OCR
        if (progressCallback) progressCallback(55, "PDF escaneado detectado: aplicando OCR visual...");
        const firstPage = await pdf.getPage(1);
        const viewport = firstPage.getViewport({ scale: 2.0 });
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        canvas.width = viewport.width;
        canvas.height = viewport.height;

        await firstPage.render({ canvasContext: ctx, viewport: viewport }).promise;
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
        return await this.processImage(blob, progressCallback);

      } catch (err) {
        console.warn("Erro no PDF.js, tentando fallback backend:", err);
      }
    }

    return "";
  }

  parseDocumentText(rawText) {
    const result = {
      nome_completo: "",
      endereco: "",
      bairro: "",
      cidade: "Goiânia",
      cep: "",
      data_nascimento: "",
      naturalidade: "",
      sexo: "",
      estado_civil: "",
      conjuge: "",
      email: "",
      telefone: "",
      whatsapp: "",
      escolaridade: "",
      formacao_academica: "",
      profissao: "",
      empresa: "",
      batizado: "",
      data_batismo: "",
      congregava_antes: "",
      onde_congregava: "",
      area_ministerial: "",
      interesse_batismo_familia: "",
      extractedFieldsCount: 0
    };

    if (!rawText) return result;

    const text = rawText.replace(/\r/g, '\n');

    // 1. Extração de E-mail
    const emailMatch = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/);
    if (emailMatch) result.email = emailMatch[0].toLowerCase();

    // 2. Extração de CEP
    const cepMatch = text.match(/\b\d{5}[-.\s]?\d{3}\b/);
    if (cepMatch) result.cep = cepMatch[0].replace(/\D/g, '').replace(/(\d{5})(\d{3})/, '$1-$2');

    // 3. Extração de Telefones / WhatsApp
    const foneMatches = text.match(/(?:\(?\b\d{2}\)?\s*)?(?:9\s*)?\d{4,5}[-.\s]?\d{4}\b/g);
    if (foneMatches && foneMatches.length > 0) {
      result.whatsapp = foneMatches[0].trim();
      if (foneMatches.length > 1) result.telefone = foneMatches[1].trim();
      else result.telefone = foneMatches[0].trim();
    }

    // 4. Extração de Datas (DD/MM/AAAA)
    const datas = text.match(/\b(0[1-9]|[12]\d|3[01])[\/\.-](0[1-9]|1[0-2])[\/\.-](19\d{2}|20\d{2})\b/g);
    if (datas && datas.length > 0) {
      result.data_nascimento = datas[0];
      if (datas.length > 1) result.data_batismo = datas[1];
    }

    // 5. Linha por Linha - Reconhecimento de Rótulos da Ficha MEVAM GYN
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lower = line.toLowerCase();

      // Nome Completo
      if ((lower.includes('nome completo') || lower.startsWith('nome:')) && !result.nome_completo) {
        const parts = line.split(/nome\s*(?:completo)?\s*[:\-]/i);
        if (parts[1] && parts[1].trim().length > 3) {
          result.nome_completo = this.cleanExtractedString(parts[1]);
        } else if (i + 1 < lines.length && !lines[i + 1].includes(':')) {
          result.nome_completo = this.cleanExtractedString(lines[i + 1]);
        }
      }

      // Endereço
      if (lower.includes('endereço') || lower.includes('endereco')) {
        const parts = line.split(/endere[çc]o\s*[:\-]/i);
        if (parts[1] && parts[1].trim().length > 3) {
          result.endereco = this.cleanExtractedString(parts[1]);
        }
      }

      // Bairro
      if (lower.includes('bairro:')) {
        const parts = line.split(/bairro\s*[:\-]/i);
        if (parts[1]) {
          result.bairro = this.cleanExtractedString(parts[1].split(/cidade/i)[0]);
        }
      }

      // Cidade
      if (lower.includes('cidade:')) {
        const parts = line.split(/cidade\s*[:\-]/i);
        if (parts[1]) {
          result.cidade = this.cleanExtractedString(parts[1].split(/cep/i)[0]);
        }
      }

      // Naturalidade
      if (lower.includes('naturalidade:')) {
        const parts = line.split(/naturalidade\s*[:\-]/i);
        if (parts[1]) result.naturalidade = this.cleanExtractedString(parts[1]);
      }

      // Sexo
      if (lower.includes('sexo:') || lower.includes('masc.') || lower.includes('fem.')) {
        if (lower.includes('(x) masc') || lower.includes('[x] masc') || (lower.includes('masc') && !lower.includes('fem'))) {
          result.sexo = "Masc.";
        } else if (lower.includes('(x) fem') || lower.includes('[x] fem') || (lower.includes('fem') && !lower.includes('masc'))) {
          result.sexo = "Fem.";
        }
      }

      // Estado Civil
      const estadosCivis = ['Casado', 'Casada', 'Solteiro', 'Solteira', 'Divorciado', 'Divorciada', 'Viúvo', 'Viúva', 'União Estável'];
      for (const ec of estadosCivis) {
        if (lower.includes(ec.toLowerCase()) && !result.estado_civil) {
          result.estado_civil = ec;
          break;
        }
      }

      // Cônjuge
      if (lower.includes('cônjuge:') || lower.includes('conjuge:')) {
        const parts = line.split(/c[ôo]njuge\s*[:\-]/i);
        if (parts[1] && parts[1].trim().length > 2) {
          result.conjuge = this.cleanExtractedString(parts[1]);
        }
      }

      // Profissão
      if (lower.includes('profissão:') || lower.includes('profissao:')) {
        const parts = line.split(/profiss[ãa]o\s*[:\-]/i);
        if (parts[1]) result.profissao = this.cleanExtractedString(parts[1]);
      }

      // Empresa
      if (lower.includes('empresa') && lower.includes(':')) {
        const parts = line.split(/empresa\s*(?:que trabalha)?\s*[:\-]/i);
        if (parts[1]) result.empresa = this.cleanExtractedString(parts[1]);
      }

      // Batizado
      if (lower.includes('batizado:')) {
        if (lower.includes('(x) sim') || lower.includes('[x] sim') || (lower.includes('sim') && !lower.includes('não'))) {
          result.batizado = "Sim";
        } else if (lower.includes('(x) não') || lower.includes('[x] não') || lower.includes('não')) {
          result.batizado = "Não";
        }
      }

      // Congregava antes
      if (lower.includes('congregava antes')) {
        if (lower.includes('(x) sim') || (lower.includes('sim') && !lower.includes('não'))) {
          result.congregava_antes = "Sim";
        } else if (lower.includes('(x) não') || lower.includes('não')) {
          result.congregava_antes = "Não";
        }
      }

      // Onde congregava
      if (lower.includes('onde?') || lower.includes('onde congregava')) {
        const parts = line.split(/onde\??\s*[:\-]/i);
        if (parts[1] && parts[1].trim().length > 2) {
          result.onde_congregava = this.cleanExtractedString(parts[1]);
        }
      }

      // Área ministerial
      if (lower.includes('área ministerial') || lower.includes('area ministerial')) {
        const parts = line.split(/[áa]rea ministerial[^\:]*[:\-]/i);
        if (parts[1] && parts[1].trim().length > 2) {
          result.area_ministerial = this.cleanExtractedString(parts[1]);
        }
      }
    }

    // Contagem de campos preenchidos
    let count = 0;
    for (const key in result) {
      if (result[key] && key !== 'cidade' && key !== 'extractedFieldsCount') count++;
    }
    result.extractedFieldsCount = count;

    return result;
  }

  cleanExtractedString(str) {
    if (!str) return "";
    return str
      .replace(/[_\.\-]{2,}/g, '') // remove underscores de formulário em branco
      .replace(/^\s*[:\-\.]\s*/, '')
      .trim();
  }
}

window.OcrEngine = OcrEngine;
