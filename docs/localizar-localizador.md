# localizar — Alterar Localizador no Projudi

## Visão Geral

O tipo `localizar` na `sequencia_cumprimento` altera o localizador de um processo
no Projudi sem expedir documento (mandado/ofício). Usa código **581** (TD - Tipo
Documental) e submete via Playwright headless + JavaScript.

## Fluxo

```
Pre-check (requests)
  │
  ▼
Playwright headless abre MovimentarProcesso
  │
  ├─ Injeta código 581
  ├─ Mostra campos ocultos (trTipoDocumento etc.)
  ├─ Clica btnBuscaMovimentacao
  ├─ Aceita alerta
  ├─ Seleciona Tipo de Documento (codTipoDocumento)
  ├─ Preenche observação
  ├─ Aba Cumprimento + btnAddCumprimento
  ├─ Configura localizador
  └─ Submit via JS (Concluir.x/y hidden)
       │
       ▼
  Verifica redirect / sucesso
```

## Configuração

No JSON da `sequencia_cumprimento` do RAG:

```json
{
    "tipo": "localizar",
    "codigo_mov": "581",
    "tipo_documento": "PESQUISA DE ENDEREÇO SISBAJUD ORDENADA",
    "tipo_localizador": "9376",
    "observacao": "Ao Localizador de Pesquisa de Endereco"
}
```

### Campos

| Campo | Obrigatório | Default | Descrição |
|---|---|---|---|
| `tipo` | sim | — | `"localizar"` |
| `codigo_mov` | não | `"581"` | Código da movimentação |
| `tipo_documento` | não | `"PESQUISA DE ENDEREÇO SISBAJUD ORDENADA"` | Rótulo do Tipo de Documento no select `codTipoDocumento` |
| `tipo_localizador` | sim | — | Código do localizador (ex: 9376) |
| `descricao_mov` | não | `"TD - Tipo Documental"` | Descrição exibida no form |
| `observacao` | não | — | Texto da observação |

## Arquivos

- `projudi/movimentacao_service.py` — `executar_requests()`: Playwright + JS submit
- `expedir_rapido.py` — extrai `tipo_documento` do JSON e passa ao service
- `projudi/rag_router.py` — cria o record (execução via `processar_fila`)

## Códigos de localizador

| Localizador | Código |
|---|---|
| Pesquisa de Endereço | 9376 |
| SISBAJUD | 22614 |
| Aguardar Cumprir Transação | 9205 |
| Aguardar Distribuição | 30586 |

## Pitfalls

### Concluir é `<input type="image">`
Não usar `page.click('#Concluir')`. Em vez disso, criar inputs hidden
`Concluir.x=10` e `Concluir.y=10` via JavaScript e chamar `form.submit()`.

### Token mismatch
Extrair HTML do Playwright e POSTar via requests session separada pode falhar
(anti-forgery token diferente). Sempre fazer o submit **dentro do mesmo
Playwright context**.

### btnAddCumprimento é necessário
O botão "Concluir" só funciona se houver ao menos uma linha no grid de
Cumprimentos. Clicar na aba "Cumprimento" + `btnAddCumprimento` é obrigatório.

### URL relativa no form action
O form usa action relativo (`/projudi/movimentacao/...`). Converter sempre:
```python
if post_url.startswith('/'):
    post_url = f'https://projudi.tjba.jus.br{post_url}'
```

### `passo` não existe no service
O dict do JSON (`passo`) só existe nos callers. Passar `tipo_documento` como
parâmetro direto ao `executar_requests()`.
