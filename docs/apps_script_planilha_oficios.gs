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
 *
 * O script procura o número em TODAS as tabelas do documento. Se ainda não
 * houver número, começa em 001/ano atual.
 */

const TOKEN = 'TROQUE-ESTE-TOKEN-POR-UM-SEGREDO';

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

    if (dados.action === 'debug') {
      return json({
        ok: true,
        documento: doc.getName(),
        tabelas: infoTabelas(tabelas)
      });
    }

    const alvo = encontrarTabela(tabelas);

    if (dados.action === 'proximo_numero') {
      if (!alvo.numero) {
        const ano = new Date().getFullYear();
        return json({
          ok: true,
          numero: '001/' + ano,
          encontrado: false,
          tabela: alvo.indice
        });
      }

      // Aceita 258, 258/2026, 258/25, 0258/2026 etc.
      const partes = alvo.numero.match(/^(\d{1,5})(?:\s*\/\s*(\d{2,4}))?$/);
      if (!partes) {
        return json({
          ok: false,
          erro: 'formato de número não reconhecido: ' + alvo.numero
        });
      }

      const largura = partes[1].length;
      const proximo = String(parseInt(partes[1], 10) + 1)
        .padStart(largura, '0');

      let numero = proximo;
      if (partes[2]) {
        let ano = partes[2];
        if (ano.length === 2) ano = '20' + ano;
        numero = proximo + '/' + ano;
      }

      return json({
        ok: true,
        numero: numero,
        encontrado: true,
        tabela: alvo.indice
      });
    }

    if (dados.action === 'registrar') {
      const tabela = alvo.tabela;
      const linha = tabela.appendTableRow();
      linha.appendTableCell(dados.numero || '');
      linha.appendTableCell(dados.data || '');
      linha.appendTableCell(dados.processo || '');
      linha.appendTableCell(dados.destinatario || '');

      doc.saveAndClose();
      return json({ok: true, tabela: alvo.indice});
    }

    return json({ok: false, erro: 'ação desconhecida'});
  } catch (err) {
    return json({ok: false, erro: String(err)});
  }
}

function encontrarTabela(tabelas) {
  // 1) Prioriza a tabela que já tem número de ofício.
  for (let i = 0; i < tabelas.length; i++) {
    const numero = ultimoNumero(tabelas[i]);
    if (numero) {
      return {tabela: tabelas[i], numero: numero, indice: i};
    }
  }

  // 2) Se nenhuma tem número, escolhe a tabela com cabeçalho de ofícios.
  for (let i = 0; i < tabelas.length; i++) {
    const tabela = tabelas[i];
    const cabecalho = cabecalhoTabela(tabela).toLowerCase();
    let score = 0;

    ['nº', 'numero', 'número', 'oficio', 'ofício', 'data',
     'processo', 'destinat', 'órgão', 'orgao'].forEach(function (termo) {
      if (cabecalho.indexOf(termo) >= 0) score++;
    });

    if (score >= 2) {
      return {tabela: tabela, numero: '', indice: i};
    }
  }

  // 3) Fallback: primeira tabela.
  return {tabela: tabelas[0], numero: '', indice: 0};
}

function normalizarTexto(texto) {
  return String(texto || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');
}

function colunaNumero(tabela) {
  if (tabela.getNumRows() === 0) return 0;

  const cabecalho = tabela.getRow(0);
  for (let c = 0; c < cabecalho.getNumCells(); c++) {
    const texto = normalizarTexto(cabecalho.getCell(c).getText());
    if (texto.indexOf('oficio') >= 0
        || texto.indexOf('numero') >= 0
        || texto.indexOf('nº') >= 0
        || texto.indexOf('n°') >= 0) {
      return c;
    }
  }

  return 0;
}

function ultimoNumero(tabela) {
  const totalLinhas = tabela.getNumRows();
  const coluna = colunaNumero(tabela);

  // Primeiro procura na coluna "Nº Ofício" (evita pegar a data).
  // Aceita número puro (258), com ano (258/2026) ou ano de 2 dígitos (258/25).
  for (let r = totalLinhas - 1; r >= 0; r--) {
    const texto = tabela.getRow(r).getCell(coluna).getText().trim();
    const m = texto.match(/(\d{1,5})(?:\s*\/\s*(\d{2,4}))?/);
    if (m) {
      return m[2] ? m[1] + '/' + m[2] : m[1];
    }
  }

  // Fallback: qualquer célula com número/ano de 4 dígitos, mas sem
  // confundir com datas (25/11/2026).
  for (let r = totalLinhas - 1; r >= 0; r--) {
    const linha = tabela.getRow(r);
    for (let c = 0; c < linha.getNumCells(); c++) {
      const texto = linha.getCell(c).getText();
      const m = texto.match(/(^|[^\d\/])(\d{1,5})\s*\/\s*(\d{4})([^\d\/]|$)/);
      if (m) {
        return m[2] + '/' + m[3];
      }
    }
  }

  return '';
}

function cabecalhoTabela(tabela) {
  if (tabela.getNumRows() === 0) return '';
  const linha = tabela.getRow(0);
  const partes = [];
  for (let c = 0; c < linha.getNumCells(); c++) {
    partes.push(linha.getCell(c).getText());
  }
  return partes.join(' ');
}

function infoTabelas(tabelas) {
  const info = [];
  for (let i = 0; i < tabelas.length; i++) {
    const tabela = tabelas[i];
    const linhas = tabela.getNumRows();
    const ultimas = [];
    const inicio = Math.max(0, linhas - 5);

    for (let r = inicio; r < linhas; r++) {
      const linha = tabela.getRow(r);
      const valores = [];
      for (let c = 0; c < linha.getNumCells(); c++) {
        valores.push(linha.getCell(c).getText());
      }
      ultimas.push(valores);
    }

    info.push({
      indice: i,
      linhas: linhas,
      colunas: linhas > 0 ? tabela.getRow(0).getNumCells() : 0,
      cabecalho: cabecalhoTabela(tabela),
      coluna_numero: colunaNumero(tabela),
      ultimo_numero: ultimoNumero(tabela),
      ultimas_linhas: ultimas
    });
  }
  return info;
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
