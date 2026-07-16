# Fluxo Completo: Solicitar e Expedir Ofício no Projudi

## Pré-requisitos

```bash
pip install playwright
python -m playwright install firefox
```

Sessão Projudi ativa (cookies no `ProjudiSession`). JSESSIONID capturado manualmente via DevTools.

## Scripts principais

| Script | Função |
|--------|--------|
| `testar_fluxo.py` | Cria doc + mov 581 + cumprimento |
| `expedir_v4.py` | Fluxo completo: 581 → CumprimentoCartorio → Redigir sem AR → FCKeditor → colar HTML → Submeter |
| `expedir_registrar.py` | Fluxo completo com Registrar: 581 → Concluir → Redigir sem AR → FCKeditor → Submeter → **Registrar** |

---

## Passo a passo completo (funcional)

### 1. MovimentarProcesso — criar movimento 581

```
page.goto("MovimentarProcesso?numeroProcesso={PROJUDI_NUM}")
```

- Preencher `#seqCategoriaMovimentacao` = `581`
- **Forçar via JS** campos ocultos (DWR validation falha):
  - `#descCategoriaMovimentacao` = "Solicitada a Expedição de Ofício"
  - `#trTipoDocumento` → `display: table-row`
  - `#divPanelCumprimento` → `display: block`
- Selecionar `select[name="codTipoDocumento"]` = `53` (Ofício)
- Preencher `#observacao`
- Expandir **Cumprimento** (clicar link `Cumprimento`)
- Selecionar `#tipoCumprimento` = `2` (OFÍCIO)
- Selecionar `#codigoDestinatario` com o destinatário correto
- Clicar `#btnAddCumprimento` (>>)
- Scroll + clicar `#Concluir`

### 2. CumprimentoCartorio — acessar ofício

```
page.goto("CumprimentoCartorio?tipo=oficio&acao=expedir")
```

- Clicar no último link **"Redigir sem AR"** (via `page.evaluate()` com `expect_navigation`)
- Navega para `ExpedirCumprimentoCartorio?codCumprimento=...`

### 3. FCKeditor — substituir HTML

- Usar `FCKeditorAPI.GetInstance('FCKeditor1')` para:
  - `SwitchToSourceMode()` — entra em modo código fonte
  - `SetHTML(html)` — substitui o conteúdo
  - `SwitchToWysiwygMode()` — volta para visualização
- Clicar **Submeter** (input type="image" src="bot-submeter.gif")
- Após Submeter, a página recarrega e aparece o botão **Registrar**
- Clicar **Registrar**

### 4. Resultado

- Ofício expedido com o HTML personalizado (template CIAP)
- Movemento 581 registrado no processo

## Observações importantes

- `codTipoDocumento=53` e `tipoCumprimento=2` são ambos "Ofício"
- Destinatário deve ser selecionado da lista (não "OUTRO DESTINATÁRIO") se existir
- DWR validation para código 581 falha ("Documento") — solução: forçar via JS
- Submeter no ExpedirCumprimentoCartorio é `<input type="image">`, não `<input type="submit">`
- "Registrar" só aparece DEPOIS de clicar Submeter (mesma página, pós-reload)
