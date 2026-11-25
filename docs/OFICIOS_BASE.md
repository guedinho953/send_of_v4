# Ofícios — fluxo base aprovado

Este documento registra o fluxo base de confecção/expedição de ofícios.
Os demais ofícios devem ser **variações deste fluxo**, mudando apenas:

- o tipo/modelo do ofício;
- as palavras-chave que identificam o tipo;
- o template HTML;
- a regra de leitura da ata;
- o destinatário padrão;
- a planilha/tabela de numeração, quando houver.

Referência legível por máquina: `docs/oficio_base_referencia.json`.

## 1. Origem: lista de ofícios pendentes

URL:

```text
/projudi/listagens/CumprimentoCartorio?tipo=oficio&acao=expedir
```

Cada linha é um `<form name="formCumprimento...">` com:

- link do processo (`DadosProcesso?numeroProcesso=...`);
- destinatário no texto da linha;
- `select[name="codModelo"]` com a lista **global** de modelos;
- link **“Redigir sem AR”**;
- `input[name="codCumprimento"]`.

Importante:

- as opções do `codModelo` são iguais em todas as linhas — **não** servem para
  descobrir o tipo da linha;
- o tipo da linha vem do texto da linha (destinatário/movimentação) ou de um
  modelo já selecionado;
- ao ler o texto da linha, remover o conteúdo dos `<select>`/`<form>`, senão
  aparecem CIAP/RPV/RPA em todas as linhas.

## 2. Processo e ata de audiência

1. Extrair o CNJ e a URL `DadosProcesso` da linha.
2. Localizar/criar o `Process`.
3. Abrir `DadosProcesso` e percorrer as movimentações.
4. Procurar eventos/documentos de audiência. Aceitar nomes:
   - `ata`
   - `audiência`
   - `audiencia`
   - `audin`  ← abreviação usada em algumas atas
5. Baixar o documento (HTML ou PDF) e extrair o texto.
6. Confirmar que a ata é do mesmo processo.
7. Extrair:
   - autor do fato (quem vai cumprir);
   - vítima;
   - prestação aceita (não a primeira proposta da ata);
   - serviço comunitário x prestação pecuniária;
   - valor, parcelas, prazo e telefone.
8. Cortar a descrição em `Faço constar...`, assinaturas e validações.

Função base: `expedir_rapido._extrair_dados_ata`.

## 3. Escolha do modelo

Para CIAP, a ata define a variação:

| Ata | Modelo |
|---|---|
| prestação de serviços | `2. CIAP(ANTIGO CEAPA) TRANSAÇÃO PENAL PRESTAÇÃO DE SERVIÇOS A COMUNIDADE` |
| prestação pecuniária | `1. CIAP(ANTIGO CEAPA) TRANSAÇÃO PENAL PRESTAÇÃO PECUNIARIA` |

O CIAP também pode aparecer como:

```text
CENTRAL INTEGRADA DE ALTERNATIVAS PENAIS PAULO AFONSO
```

Por isso os aliases `CIAP`, `CENTRAL INTEGRADA` e `ALTERNATIVAS PENAIS` são
tratados como o mesmo tipo.

## 4. Número do ofício

Fonte principal: **planilha/tabela do Google Docs**.

Prioridade de integração:
1. Web App do Apps Script (`GOOGLE_OFICIOS_WEBHOOK_URL`) — usa o Gmail/conta
   que já tem acesso ao documento;
2. conta de serviço (`GOOGLE_SERVICE_ACCOUNT_FILE`).

Regra:

```text
último número da tabela + 1
```

Exemplo: `012/2026` → `013/2026`.

Fallback quando a planilha não está configurada: numeração local do projeto.

O número é usado no HTML **antes** da expedição e a linha é gravada na
planilha **depois** do `Registrar`.

## 5. Assinatura

Assinantes configurados:

| Chave | Nome | Cargo |
|---|---|---|
| `ivan` | IVAN GUEDES DA SILVA | SECRETÁRIO EM SUBSTITUIÇÃO |
| `mauro` | MAURO EMILIO VIANA DA SILVA MOREIRA | SECRETÁRIO |

Padrão: `ivan`.

A troca é feita por pós-processamento (`_aplicar_assinatura`), para funcionar
mesmo em modelos antigos que tenham o nome do Mauro fixo no HTML.

## 6. Expedição no Projudi

Ordem obrigatória:

1. selecionar o modelo correto no `codModelo`;
2. clicar no link real **“Redigir sem AR”** da linha;
3. no editor, colar o HTML confeccionado;
4. clicar em **Submeter**;
5. clicar em **Registrar**.

Depois do sucesso, inserir a linha na planilha Google com:

```text
número | data | processo | destinatário
```

## 7. Destinatário

- CIAP: `CENTRAL INTEGRADA DE ALTERNATIVAS PENAIS PAULO AFONSO`.
- Demais ofícios: extrair da linha do `CumprimentoCartorio`, removendo CNJ,
  nome do juiz, textos de “Redigir…” e a movimentação.

## 8. Como criar uma variação

Para um novo tipo de ofício:

1. copiar `expedir_oficios_por_tipo.py` ou criar um `tipo_efetivo` novo;
2. ajustar os aliases/palavras-chave;
3. apontar para o `DocumentTemplate` correto;
4. ajustar a regra de ata (ou desativar a leitura de ata se não houver);
5. ajustar o destinatário padrão;
6. manter o mesmo fluxo `Redigir sem AR → FCKeditor → Submeter → Registrar`;
7. manter a numeração pela planilha quando o ofício entrar na mesma sequência.

## 8.1 Variação aprovada: 20º BPM — Apresentação de Policiais

- Filtro da linha: destinatário/texto contendo `20 BPM` ou `20º BPM`.
- Template: `Ofício 20º BPM — Apresentação de Policiais` (template novo).
- Fonte dos dados:
  - último despacho/movimentações do processo;
  - data e hora da audiência;
  - testemunhas/policiais militares cadastrados como terceiros ou citados
    no despacho.
- Destinatário fixo:
  - `Ten Cel PM EMÍLIA SILVA COSTA NETA`;
  - `Comandante do 20º BPM`;
  - `bpm20.cmd@pm.ba.gov.br`.
- Cópia de e-mail:
  - `anilton.estevam@pm.ba.gov.br`.
- O envio de e-mail agora aceita vários destinatários separados por
  vírgula ou ponto e vírgula.
- Se a data da audiência ou os policiais não forem encontrados, o item é
  pulado em vez de gerar um ofício incompleto.

## 9. Checklist de teste

- [ ] A linha correta foi encontrada (não todas).
- [ ] O processo foi localizado.
- [ ] A ata foi baixada (inclusive `audin`).
- [ ] O autor do fato está correto.
- [ ] Serviço x pecuniária está correto.
- [ ] O telefone veio da ata.
- [ ] A descrição parou em “Faço constar”.
- [ ] O número da planilha é o último + 1.
- [ ] A assinatura escolhida está correta.
- [ ] O ofício foi registrado no Projudi.
- [ ] A linha foi adicionada na planilha.
