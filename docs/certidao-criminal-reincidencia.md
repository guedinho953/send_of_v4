# Certidão Criminal — Reincidência (Art. 76, Lei 9.099/95)

> **Atualizado em 2026-07-31** — fluxo completo validado no processo
> 0001708-74.2026.8.05.0191 (mov "Juntada de Certidão" confirmada no Projudi).

## Lógica

1. Extrair os **autores do fato** da ata de audiência do processo
   (`_extrair_dados_ata()` — lê o PDF/HTML da ata no DadosProcesso).
2. **Buscar no Projudi pelo nome** (`BuscaService.buscar_por_nome`):
   - `codNatureza=2` (Criminal)
   - `codVara=-1` → opção **"Selecione Para Busca"** (vara SEM nome) =
     busca em **TODAS as varas**. ⚠️ O default do form é a vara do usuário
     (411 = 2ª VSJ PAULO AFONSO) — sem selecionar `-1` a busca não acha
     processos de outras varas.
3. **REGRA DE SEGURANÇA**: se a busca retornar **≠ 1 processo** (0 ou >1),
   a sequência é **ABORTADA** — a certidão NÃO é feita (ambiguidade).
   Só gera certidão quando o nome retorna EXATAMENTE 1 processo.
4. Gerar a certidão: 1 autor → texto singular; N autores → texto plural.

## Fluxo da sequência (RAGExample.sequencia_cumprimento)

```json
[
  {
    "tipo": "buscar_processo",
    "cod_vara": "-1",
    "cod_natureza": "2"
  },
  {
    "tipo": "certidao_criminal",
    "codigo_mov": "581",
    "observacao": "Certidão Criminal - Art. 76 Lei 9.099/95",
    "tipo_documento": "Certidão"
  }
]
```

- `tipo_documento` do passo `certidao_criminal` DEVE ser `"Certidão"`
  (label exato) — o select `codTipoDocumento` do Mov581 usa **valor 37**.
  ⚠️ `"CUMPRIMENTO"` NÃO existe no select (o mais próximo é 55 "Cumprimento
  Genérico") — o 581 fica sem tipo de documento e o Concluir falha.
- Os nomes da busca são **dinâmicos** (extraídos da ata), nunca hardcoded
  no JSON.

## Inserção no Projudi (`MovimentacaoService.executar_requests`)

Ordem dos passos (PASSO 3 → certidão, depois movimentação):

1. **Inserir documento** (PASSO 3): `SelectArquivo=DigitarTexto` →
   `codDescricao1=37` (Certidão) → campo descricao → clicar `redigirTexto()`
   → FCKeditor → `SetHTML(certidao_html)` → **Submeter**.
2. **Assinar** (após o Submeter):
   - Clique automático no Assinar (`img[src*="bot-assinar"]`) — funciona
     quando a assinatura está SALVA no Projudi (só precisa clicar).
   - Se aparecer campo `input[name="senha"]` → preenche automaticamente
     com `user.projudi_password` e clica em Assinar de novo (2 cliques).
   - Se `projudi_password` vazio → modo manual: scroll automático,
     screenshot em `/tmp/certidao_assinatura.png`, espera até 3 min.

### Diálogo de assinatura fica num IFRAME (`popupFrame`)

O `#senha` e o botão Assinar (`<img src=".../botoes/bot-assinar.gif">`) NÃO
estão no frame principal — estão no iframe **`popupFrame`**, cuja URL é
`/projudi/acoes/UploadDocumento?docOnline=true&codDescricao=37&descricao=`.

Mapa observado no momento exato da assinatura (2026-08):

```
🖼️ [0] name=''           url=/projudi/acoes/DigitarTexto?...  ← ASSINAR (1º clique, frame principal)
🖼️ [1] name='popupFrame' url=/projudi/acoes/UploadDocumento?...codDescricao=37  ← SENHA + ASSINAR (diálogo)
```

Consequências para a automação (`movimentacao_service.py`):

1. O `#senha` **só aparece DEPOIS** do 1º clique em Assinar — nada de
   checar `count()` uma única vez (dava 0 e pulava o preenchimento).
   Usar `_procurar_campo_senha()` que espera até 10s e procura em
   **todos os frames** (usando `frame.locator(e)` via `page.frames`).
2. O botão de confirmação está **no mesmo frame da senha**. Sempre
   procurá-lo `popupFrame`/frame que tem `#senha` (alvo exato = menos
   varredura genérica), com fallback para varrer todos os frames.
   Helper: `_clicar_botao_assinar()`.
3. `_logar_frames(page)` descreve todos os frames no momento da assinatura
   (usado para diagnóstico e para manter esta documentação).

⚠️ **NUNCA inserir a certidão duas vezes** — o bloco duplicado de inserção
foi desativado (`if certidao_html and False`). A certidão entra UMA vez
(PASSO 3), senão o usuário é obrigado a assinar 2x e o estado se perde.

## Certidão Criminal NEGATIVA (2026-08) — templates no admin

O fluxo agora gera a certidão a partir de **DocumentTemplate** (tipo `certidao`),
criados por `criar_templates_certidao.py`:

| Template | id | Quando |
|---|---|---|
| `Certidão Criminal Negativa (1 Autor)` | 9 | ata com 1 autor |
| `Certidão Criminal Negativa (Vários Autores)` | 10 | ata com N autores — **todos** retornaram exatamente 1 processo na busca |

- Layout igual ao Ofício CIAP, com **brasão embutido** (`brasaoPetroBranco.jpg`),
  corpo parametrizado: `{{ processo }}`, `{{ autor }}` / `{{ autores_lista }}` +
  `{{ autores_texto }}`, `{{ vitima }}`, `{{ servidor }}`, `{{ data }}`.
- **Regra multi-autor:** o passo `buscar_processo` busca **cada** autor
  individualmente; se QUALQUER um retornar ≠1 processo, a sequência é
  abortada (nada é feito — análise humana). Só gera a certidão se TODOS
  retornarem exatamente 1 (todos negativos).
- **Enumeração:** a certidão lista cada autor ("1. NOME, 2. NOME2") e a
  **observação da Mov581** também: `Certidão Criminal NEGATIVA - Autor do
  Fato 1: X; Autor do Fato 2: Y; ...`.
- **Persistência:** o HTML final é salvo em `GeneratedDocument` (como
  mandados/ofícios) quando a execução conclui.
- Fallback: se o template não existir, usa a geração antiga
  (`_gerar_html_certidao`).

## HTML da certidão (`_gerar_html_certidao()` em `expedir_rapido.py`)

- Base de formatação = template do **Ofício CIAP** (DocumentTemplate id=5):
  Times New Roman 12pt, cabeçalho do juízo (Poder Judiciário → TJBA →
  2ª Vara → Paulo Afonso), `<hr>`, endereço/contato, corpo Courier New
  10pt com `text-indent:80px`.
- **Brasão do TJBA**: `https://projudi.tjba.jus.br/projudi/imagens/
  brasaoPetroBranco.jpg` (o MESMO do modelo RPA dos ofícios, 80px,
  centralizado). ⚠️ `/projudi/imagens/brasao.jpg` é **404** (não usar).
  O DigitarTexto abre com `codModelo=-1` (editor vazio) — não há modelo pra
  extrair o brasão, então ele vai DIRETO no HTML.
- Assinatura centralizada: data com `margin-bottom:16px` afastada do nome.
- Rodapé: nota da Lei 11.419/06 + nº do processo (com `margin-top:16px` e
  `margin-bottom:24px`).

## WSLg (navegador abrindo em BRANCO)

Após reiniciar o WSL, o Firefox do Playwright (headless=False) pode abrir
sem renderizar (janela branca / ícone pinguim). Fix aplicado em
`movimentacao_service.py` E `busca_service.py`:

```python
_FIREFOX_ENV = {**os.environ, 'MOZ_DISABLE_GPU_SANDBOX': '1',
                'LIBGL_ALWAYS_SOFTWARE': '1'}
_FIREFOX_PREFS = {'gfx.webrender.software': True}
```

Se a janela abrir em branco de novo: reiniciar o WSL (WSLg volta limpo).

## Arquivos envolvidos

| Arquivo | Papel |
|---|---|
| `expedir_rapido.py` | Branch `certidao_criminal` + `_gerar_html_certidao()` + branch `buscar_processo` |
| `projudi/movimentacao_service.py` | `executar_requests()` — inserção, assinatura, 581, Concluir |
| `projudi/busca_service.py` | `BuscaService.buscar_por_nome()` — busca por nome (vara -1, natureza 2) |
| `projudi/services.py` | `ProjudiService._get_session_from_cookies()` — sessão 4 camadas |
| RAGExample 2443 | Sequência [buscar_processo, certidao_criminal] |

## Placeholders do texto

| Trecho | Origem |
|---|---|
| Processo | `proc_num` (CNJ) |
| Autor(es) do fato | `dados_ata['autores_do_fato']` (ata PDF) |
| Vítima | `dados_ata['vitima']` (ata PDF) |
| Data | `date.today().strftime('%d/%m/%Y')` |
| Servidor | `user.full_name` |
