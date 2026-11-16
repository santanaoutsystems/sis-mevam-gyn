/**
 * SignaturePad - Módulo de Assinatura Digital Tipo Rúbrica
 * Suporte a iPhone (Touch), Android, Caneta Stylus e Desktop
 * Traçado vetorial suave com anti-aliasing e alta resolução (Retina/DPI)
 */

class SignaturePad {
  constructor(canvasElement, options = {}) {
    this.canvas = canvasElement;
    this.ctx = this.canvas.getContext('2d');
    this.options = Object.assign({
      color: '#003399',      // Cor caneta executiva padrão
      lineWidth: 2.5,
      watermarkText: 'RÚBRICA DIGITAL'
    }, options);

    this.points = [];
    this.history = [];
    this.isDrawing = false;
    this.hasSignature = false;

    this.initCanvasSize();
    this.bindEvents();

    window.addEventListener('resize', () => this.handleResize());
  }

  initCanvasSize() {
    const ratio = Math.max(window.devicePixelRatio || 1, 1);
    const rect = this.canvas.getBoundingClientRect();
    
    // Configurar tamanho real para resolução nítida
    const width = rect.width || this.canvas.offsetWidth || 500;
    const height = 180; // Altura ideal para celular e pc

    this.canvas.width = width * ratio;
    this.canvas.height = height * ratio;
    this.ctx.scale(ratio, ratio);

    this.ctx.lineCap = 'round';
    this.ctx.lineJoin = 'round';
    this.ctx.strokeStyle = this.options.color;
    this.ctx.lineWidth = this.options.lineWidth;
  }

  handleResize() {
    // Preservar traço se houver
    if (this.hasSignature) {
      const data = this.toDataURL();
      this.initCanvasSize();
      const img = new Image();
      img.onload = () => {
        this.ctx.drawImage(img, 0, 0, this.canvas.offsetWidth, this.canvas.offsetHeight);
      };
      img.src = data;
    } else {
      this.initCanvasSize();
    }
  }

  bindEvents() {
    // Mouse Events
    this.canvas.addEventListener('mousedown', (e) => this.startDrawing(e));
    this.canvas.addEventListener('mousemove', (e) => this.draw(e));
    window.addEventListener('mouseup', () => this.stopDrawing());

    // Touch & Pointer Events (iPhone / Android)
    this.canvas.addEventListener('touchstart', (e) => {
      e.preventDefault();
      const touch = e.touches[0];
      this.startDrawing(touch);
    }, { passive: false });

    this.canvas.addEventListener('touchmove', (e) => {
      e.preventDefault();
      const touch = e.touches[0];
      this.draw(touch);
    }, { passive: false });

    this.canvas.addEventListener('touchend', (e) => {
      e.preventDefault();
      this.stopDrawing();
    }, { passive: false });
  }

  getCoordinates(event) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: (event.clientX || event.pageX) - rect.left,
      y: (event.clientY || event.pageY) - rect.top
    };
  }

  startDrawing(e) {
    this.isDrawing = true;
    const coords = this.getCoordinates(e);
    this.points = [coords];

    this.ctx.beginPath();
    this.ctx.moveTo(coords.x, coords.y);

    // Ocultar marca d'água na primeira pincelada
    const wm = document.getElementById('signatureWatermark');
    if (wm) wm.style.opacity = '0';
  }

  draw(e) {
    if (!this.isDrawing) return;
    const coords = this.getCoordinates(e);
    this.points.push(coords);

    if (this.points.length > 2) {
      const p1 = this.points[this.points.length - 2];
      const p2 = this.points[this.points.length - 1];
      const midPoint = {
        x: (p1.x + p2.x) / 2,
        y: (p1.y + p2.y) / 2
      };

      this.ctx.quadraticCurveTo(p1.x, p1.y, midPoint.x, midPoint.y);
      this.ctx.stroke();
    } else {
      this.ctx.lineTo(coords.x, coords.y);
      this.ctx.stroke();
    }

    this.hasSignature = true;
  }

  stopDrawing() {
    if (!this.isDrawing) return;
    this.isDrawing = false;
    this.ctx.closePath();
    this.saveState();
  }

  saveState() {
    this.history.push(this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height));
    if (this.history.length > 20) this.history.shift();
  }

  undo() {
    if (this.history.length > 1) {
      this.history.pop();
      const prevState = this.history[this.history.length - 1];
      this.ctx.putImageData(prevState, 0, 0);
    } else if (this.history.length === 1) {
      this.clear();
    }
  }

  clear() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.history = [];
    this.hasSignature = false;
    this.points = [];

    const wm = document.getElementById('signatureWatermark');
    if (wm) wm.style.opacity = '0.6';
  }

  setColor(color) {
    this.options.color = color;
    this.ctx.strokeStyle = color;
  }

  setLineWidth(width) {
    this.options.lineWidth = width;
    this.ctx.lineWidth = width;
  }

  isEmpty() {
    return !this.hasSignature;
  }

  toDataURL(format = 'image/png') {
    return this.canvas.toDataURL(format);
  }
}

window.SignaturePad = SignaturePad;
