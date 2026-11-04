// SIS MEVAM-GYN: envio de e-mail pela conta Gmail da Secretaria (grátis).
// Cole este código em https://script.google.com (logado no Gmail da Secretaria),
// troque o SEGREDO por uma frase longa só sua e implante como "App da Web".
// O mesmo SEGREDO vai na variável EMAIL_GOOGLE_SEGREDO do Render.
// Mutirão de fichas: o ID da pasta do Drive vai na variável MUTIRAO_DRIVE_PASTA do Render.
const SEGREDO = 'TROQUE-POR-UMA-FRASE-LONGA-E-SECRETA';

function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.segredo !== SEGREDO) return saida({ ok: false, erro: 'segredo inválido' });
    if (d.acao === 'drive') {  // Mutirão de fichas: grava a foto da ficha na pasta do Drive
      const pasta = DriveApp.getFolderById(d.pasta);
      const arq = pasta.createFile(Utilities.newBlob(Utilities.base64Decode(d.dados), d.mime, d.nome));
      return saida({ ok: true, id: arq.getId() });
    }
    MailApp.sendEmail({ to: d.para, subject: d.assunto, body: d.corpo, name: d.nome || 'SIS MEVAM-GYN' });
    return saida({ ok: true, restantes_hoje: MailApp.getRemainingDailyQuota() });
  } catch (err) {
    return saida({ ok: false, erro: String(err) });
  }
}

// Rode esta função uma vez pelo editor para autorizar o envio de e-mail e a gravação no Drive.
function autorizar() {
  DriveApp.getRootFolder();
  MailApp.sendEmail(Session.getActiveUser().getEmail(), 'SIS MEVAM-GYN: autorização ok',
                    'O script de envio de e-mail e do Drive está autorizado.');
}

function saida(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
