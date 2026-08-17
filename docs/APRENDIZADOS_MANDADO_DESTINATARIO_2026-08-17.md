# Aprendizados sobre Seleção de Destinatário em Mandados — send_of_v4
> Consolidado em 2026-08-17. Problema: mandado não expedia sem destinatário selecionado.

> **Problema original:** "não solicitou o destinatário e nem expediu o mandado"
> **Solução:** Loop por destinatário + fallback "todos do polo"

> ---

## 1. Raiz do Problema

O campo `#codigoDestinatario` no Projudi é **SINGLE-SELECT** (1 opção só).
O código antigo tentava:
```python
# ERADO — tenta selecionar TODOS os valores de uma única vez
valores = [o.get_attribute('value') for o in opts if ...]
page.select_option('#codigoDestinatario', valores)  # ❌ Falha!
page.click('#btnAddCumprimento')  # 1 clique só
```

O **Projudi** rejeita: `select_option` com múltiplos valores em field single-select.

### Diagnóstico do usuário:
> "está clicando em adicionar cumprimento antes de selecionar destinatario"

**Isso estava certo!** O código clicava `#btnAddCumprimento` SEM antes ter selecionado um valor no dropdown. O Projudi validava: "é obrigatório selecionar destinatário".

## 2. Solução Aplicada

### Padrão Correto (igual ao `_expedir_mandado`):

```python
# CORRETO — loop: para CADA destinatário, seleciona UM + Add Cumprimento
for ot, ov in alvos:  # (texto, value
    page.select_option('#codigoDestinatario', ov)   # seleciona 1
    _t.sleep(0.3)
    page.click('#btnAddCumprimento')                # adiciona 1 mandado
    _t.sleep(0.8)
```

### Regra de Filtragem:
1. **Tenta casar `parte_nome`** (nome do réu via `mandado_polo`)
2. **Se não achar** → **fallback**: usa TODAS as opções válidas do dropdown
   - Isso corresponde ao solicitado: "se não achar o específico, use fallback todos do polo"
3. **Ignora placeholders**: "Selecione um destinatário", "OUTRO DESTINATÁRIO"

### Dropdown Real (exemplo):
```html
<select name="codigoDestinatario">
  <option value="-1">Selecione um destinatário</option>     ← IGNORAR
  <option value="13628410">BRADESCO SAUDE S/A</option>
  <option value="13628411">JULIA LOPES FILHA</option>
  <option value="-2">OUTRO DESTINATÁRIO</option>           ← IGNORAR
</select>
```

## 3. Mudanças no Código (arquivos modificados)

### `projudi/movimentacao_service.py` — Método `_preencher_solicitar_mandado`:

1. **Assinatura**: Adicionou `parte_nome: 'str | None' = '')` para receber o nome do destinatário
2. **Lógica de fallback**: Se não achar nome específico → seleciona todas as opções do dropdown (todos do polo)
3. **Loop por destinatário**: Para cada (texto, value) no dropdown:
   - `select_option('#codigoDestinatario', value)` → seleciona 1
   - `click('#btnAddCumprimento')` → adiciona 1 mandado na grade

### `RAG #2528` (`docs/referencia-rapida-sequencia.json`):

| Campo | Valor | Significado |
|-------|-------|-------------|
| `polo` | `reu_especifico` | Busca réu específico via histórico |
| `mandado_polo` | `reu_especifico` | Define destinatário no formulário |
| `fallback_polo` | `res` | Se não achar → todos os réus |
| `fallback` | `solicitar_expedicao` | Passo correto (não `solicitar_expecidao`) |
| `expedir_ar` | `False` | Remove AR digital do fluxo principal |
| `fallback_ar` | `True` | AR como fallback opcional |
| `assinar_ar` | `False` | Sem assinatura |

## 4. O que Funcionou (Resultado do Teste)

```
✅ Linha de cumprimento: Mandado (tipoCumprimento=4, subtipo=11)
✅ Mandado destinatário: IVAN DE SOUZA SANTOS (9343253)
✅ Mandado destinatário: NATAN GABRIEL SANTOS DA SILVA (9343254)
✅ Mandado destinatário: PAULO MIGUEL SANDES DA SILVA (9343255)
✅ Cumprimento #209 registrado (cumprido)
```

**3 mandados gerados** — 1 para cada destinatário do polo réu.

## 5. O que Falhou / Requer Ajuste

| Item | Status |
|------|--------|
| AR digital no fluxo principal | `expedir_ar: false` remove erro de `select name="tipo"` |
| Modelo #9 (TEOR DO DESPACHO) | ✅ Já criado, mas não testado neste fluxo |
| Documento completo (FCKeditor) | Próximo passo: verificar se cada mandado gera o HTML |
| Fallback para autores | Simetria: `polo: autor_especifico` + `fallback_polo: autores` |

## 6. Checklist de Backup

### ✅ Local (já commitado):
- `docs/APRENDIZADOS_MANDADO_DESTINATARIO_2026-08-17.md` — documento novo
- `projudi/movimentacao_service.py` — método atualizado
- `expedir_rapido.py` — configuração JSON RAG #2528
- `RAG #2528` — flags corrigidas

### 📦 Backups (já existentes):
- `/home/ivan/backups/` — 7 snapshots SQL (.sql.gz) de 04/08 a 13/08
- `/home/ivan/PythonProjects/send_of_v4/BACKUP_*` — backups de alterações
- Git local (`git status` mostra arquivos modificados)

### 💾 Recomendação de E: (Drive):
```
Copy these key files to /mnt/e/:
- docs/APRENDIZADOS_MANDADO_DESTINATARIO_2026-08-17.md
- git diff dos arquivos modificados (projudi/movimentacao_service.py, expedir_rapido.py)
- Estudo dos arquivos .sql.gz anteriores para comparação
```

## 7. Próximos Passos (Checklist)

- [ ] Testar se cada um dos 3 mandados gerados tem documento completo (FCKeditor + modelo #9)
- [ ] Aplicar simetria: `polo: autor_especifico` + `fallback_polo: autores` para mandados contra autores
- [ ] Documentar o fallback de AR (`fallback_ar: true`) em caso de necessidade futura
- [ ] Verificar se `solicitar_mandado: true` + passo de mandado no JSON causa duplicação

--- 

> "Se não achar o destinatário específico → fallback: todos do polo"
> 
> *Lógica aplicada no método `_preencher_solicitar_mandado` com loop por destinatário.*
