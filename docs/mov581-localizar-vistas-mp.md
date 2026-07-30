# Mov581: localizar, vistas_mp e certidão no Projudi

## Arquitetura

Tudo na página **MovimentarProcesso** com código **581**.

A página tem:
- Campos de código + descrição + observação
- Aba **Cumprimento** — grid MP (linhas de cumprimento)
- **Abaixo do grid MP**: SelectArquivo, codDescricao1, redigirTexto
- Painel de localizador
- Painel de envio a órgão externo
- Botão Concluir

## Fluxo

```
Pre-check (requests)
  ├─ extrair_localizador() — pula se já definido
  └─ extrair_classe() — detecta cível/criminal

Playwright headless abre MovimentarProcesso
  │
  ├─ 1. Injeta código 581
  ├─ 2. Mostra campos ocultos (trTipoDocumento, rowDados, divPanelCumprimento)
  ├─ 3. Clica btnBuscaMovimentacao + aceita alerta
  ├─ 4. Seleciona Tipo Documento (codTipoDocumento)
  ├─ 5. [vistas_mp] Expande painel envio órgão externo + enviaMP + Núcleo
  ├─ 6. Preenche observação
  ├─ 7. Aba Cumprimento + btnAddCumprimento (MP-1, obrigatório)
  │
  ├─ 8. [certidao] Abaixo do grid MP:
  │      ├─ Radio SelectArquivo=DigitarTexto
  │      ├─ Select codDescricao1=37 (Certidão)
  │      ├─ Campo descricao
  │      ├─ Link redigirTexto() → FCKeditor
  │      ├─ Escreve texto da certidão
  │      ├─ Submeter
  │      ├─ Assinar (bot-assinar.gif)
  │      ├─ Preenche senha (input name="senha")
  │      └─ Assinar novamente (bot-assinar.gif)
  │
  ├─ 9. Localizador (select via JS + clica Adicionar)
  └─ 10. Submit JS (Concluir.x/y hidden + form.submit())
        └─ Verifica redirect DadosProcesso
```

## Seletores

| Elemento | Seletor |
|---|---|
| Select tipo documento | `select[name="codTipoDocumento"]` |
| Buscar movimentação | `#btnBuscaMovimentacao` |
| Painel localizador | `#imgBotao_panelLocalizador` |
| Select localizador | `#codTipoLocalizador` |
| Botão adicionar localizador | `img[src*="bot-adicionar"]` |
| Painel envio órgão externo | `#imgBotao_panelEnvioOrgaoExterno` |
| Checkbox enviaMP | `input[name="enviaMP"]` |
| Select núcleo MP | `select[name="codNucleoMP"]` |
| Aba cumprimento | `a:text('Cumprimento')` |
| Add cumprimento | `#btnAddCumprimento` |
| Radio digitar texto | `input[name="SelectArquivo"][value="DigitarTexto"]` |
| Select descrição doc | `select[name="codDescricao1"]` |
| Link redigir texto | `a[href*="redigirTexto"]` |
| Concluir | JS submit com Concluir.x/y hidden |

## Códigos

### Localizador
| Código | Nome |
|---|---|
| 9376 | Pesquisa de Endereço |
| 22614 | SISBAJUD |
| 15286 | Aguardar Decurso do Prazo |
| 9205 | Aguardar Cumprir Transação |
| 30586 | Aguardar Distribuição |

### Descrição (codDescricao1)
| Código | Nome |
|---|---|
| 37 | Certidão |
| 1006 | Ato Ordinatório |
| 2 | Citação |
| 5 | Intimação |
| 88 | BO |

### Núcleo MP
| Código | Nome |
|---|---|
| 31 | Paulo Afonso |
| 1 | Turmas Recursais |
