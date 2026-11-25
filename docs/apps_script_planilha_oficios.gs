/**
 * Planilha de ofícios no Google Docs via Apps Script.
 *
 * Como instalar:
 * 1. Abra o Google Docs com a conta que tem acesso à tabela.
 * 2. Extensões → Apps Script.
 * 3. Cole este código.
 * 4. Troque o TOKEN abaixo por uma senha longa.
 * 5. Implantar → Nova implantação → App da Web.
 *    - Executar como: Eu
 *    - Quem tem acesso: Qualquer pessoa
 * 6. Copie a URL do App da Web e configure no .env:
 *    GOOGLE_OFICIOS_WEBHOOK_URL=...
 *    GOOGLE_OFICIOS_WEBHOOK_TOKEN=o-mesmo-token
 */

const TOKEN = 'TROQUE-ESTE-TOKEN-POR-UM-SEGREDO';
const TABELA_INDEX = 0;

function doPost(e) {
  try {
    const dados = JSON.parse((e && e.postData && e.postData.contents) || '{}');

    if (TOKEN && dados.token !== TOKEN) {
      return json({ok: false, erro: 'token inválido'});
    }

    const doc = DocumentApp.getActiveDocument();
    const tabelas = doc.getBody().getTables();
    if (!tabelas.length) {
      return json({ok: false, erro: 'documento sem tabela'});
    }

    const tabela = tabelas[TABELA_INDEX] || tabelas[0];

    if (dados.action === 'proximo_numero') {
      const ultimo = ultimoNumero(tabela);
      if (!ultimo) {
        return json({ok: false, erro: 'número não encontrado na tabela'});
      }
      const partes = ultimo.match(/(\d+)\s*\/\s*(\d{4})/);
      const largura = partes[1].length;
      const proximo = String(parseInt(partes[1], 10) + 1)
        .padStart(largura, '0');
      return json({ok: true, numero: proximo + '/' + partes[2]});
    }

    if (dados.action === 'registrar') {
      const linha = tabela.appendTableRow();
      linha.appendTableCell(dados.numero || '');
      linha.appendTableCell(dados.data || '');
      linha.appendTableCell(dados.processo || '');
      linha.appendTableCell(dados.destinatario || '');
      doc.saveAndClose();
      return json({ok: true});
    }

    return json({ok: false, erro: 'ação desconhecida'});
  } catch (err) {
    return json({ok: false, erro: String(err)});
  }
}

function ultimoNumero(tabela) {
  const totalLinhas = tabela.getNumRows();
  for (let r = totalLinhas - 1; r >= 0; r--) {
    const linha = tabela.getRow(r);
    const totalCelulas = linha.getNumCells();
    for (let c = totalCelulas - 1; c >= 0; c--) {
      const texto = linha.getCell(c).getText();
      const m = texto.match(/(^|[^\d\/])(\d{1,5})\s*\/\s*(\d{4})([^\d\/]|$)/);
      if (m) {
        return m[2] + '/' + m[3];
      }
    }
  }
  return '';
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
