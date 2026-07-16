# Progresso - 15/07/2026

## Fluxo de Solicitação de Ofícios (parte 1 concluída)

### Concluído hoje
- Playwright + Firefox próprio instalado no venv (headful, visível)
- Script `testar_fluxo.py` com fluxo completo de criação da mov 581:
  1. Preenche `seqCategoriaMovimentacao = 581`
  2. Clica na seta (btnBuscaMovimentacao - ou força JS)
  3. Mostra campos ocultos via JS (`trTipoDocumento`, `divPanelCumprimento`)
  4. Seleciona `codTipoDocumento = 53` (Ofício)
  5. Preenche `observacao`
  6. Clica "Cumprimento(s) Cartório"
  7. Seleciona `tipoCumprimento = 2` (OFÍCIO)
  8. Seleciona destinatário (`codigoDestinatario`)
  9. Clica `>>` (btnAddCumprimento)
  10. Clica `Concluir`

### Resultado
- Ofício JANO foi solicitado com sucesso (mov 581 criada + cumprimento gerado)
- Ofício aparece em **Cumprimento Cartório > Para Expedir > Ofícios**

### Pendente (parte 2)
- Substituir HTML do ofício genérico pelo template gerado:
  - Navegar no link do ofício em CumprimentoCartorio
  - Clicar `btnCodigoFonte`
  - Colar HTML em `codigoFonte`
  - Clicar `btnSalvarCodigoFonte`

### Arquivos relevantes
- `testar_fluxo.py` - script funcional do fluxo completo
- `processes/management/commands/expedir_oficio_projudi.py` - comando Django refatorado
