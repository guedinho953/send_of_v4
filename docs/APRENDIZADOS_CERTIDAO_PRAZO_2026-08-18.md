# APRENDIZADOS — Certidão de Prazo: Flag "Se Decorreu" + Placeholders de Destinatário (2026-08-18)

## Observação Importante

O usuário destacou a necessidade de uma flag **"se decorreu ou não"** na certidão de prazo, e também de **placeholders para o destinatário** (autor, réu, ambos, autor específico, réu específico).

## Como Funciona Hoje (Configuração Existente)

### Campo `polo_prazo` nas RAGs
As RAGs de intimação já têm o campo `polo_prazo` na sequência_cumprimento. Os valores observados:

| RAG ID | `polo_prazo` | Observação |
|--------|--------------|------------|
| 2525 | `reu` | Reu como destinatário |
| 2498 | (vazio) | Sem configuração explícita |
| 2499 | (vazio) | Sem configuração explícita |
| 2507 | (vazio) | Sem configuração explícita |
| 2508 | (vazio) | Sem configuração explícita |
| 2529 | (vazio) | Liminar concedida/mandado |
| 2530 | (vazio) | Liminar não concedida |
| 2531 | (vazio) | Liminar concedida/solicitar_expedicao |
| 2533 | (vazio) | Despacho com eventos |
| 2534 | (vazio) | Desarquivamento gratuidade |

### Flags de Controle nas RAGs

| Campo | Significado | Padrão |
|-------|-------------|--------|
| `observacao_prazo` | Se a contagem de prazo deve ir para a observação da movimentação | `True` / `False` |
| `expede_certidao_prazo` | Se deve ser expedida a Certidão de Prazo (documento à parte) | `True` / `False` |
| `polo_prazo` | **Destinatário da certidão**: `autor`, `reu`, `ambos`, ou vazio | Configurado explicitamente |

## Flag "Se Decorreu ou Não"

### Como Implementar

O despacho diz: *"Certifique-se o decurso do prazo para impugnação à penhora. Em caso positivo, intime-se..."*

Isso sugere que a certidão deveria indicar se:
- ✅ **Decorreu** — O prazo venceu (término passou)
- ⏳ **Em andamento** — Ainda dentro do prazo (data corrente < termo final)
- ❓ **Não decorreu** — Prazo não foi atingido ainda

### Configuração no RAGExample

No modelo `RAGExample`, a flag seria adicionada na sequência. Exemplo:

```json
{
  "tipo": "intimacao_eletronica",
  "polo_prazo": "ambos", 
  "observacao_prazo": true,
  "expede_certidao_prazo": true,
  "flags_prazo": {
    "informar_decursao": true  // NOVO: informar se decorreu ou não
  }
}
```

### Como o Serviço Lê Isso

No `projudi/cumprimento_service.py`, o método `_config_prazo_do_rag` lê a configuração. Se houver um bloco `flags_prazo`, ele poderá ativar o modo "informar decursao".

## Placeholders de Destinatário (Autor/Reu)

### Problema

O usuário observou que a certidão pode ter destinatário variável:
1. **Autor** — Quem moveu o processo (exequente, autora)
2. **Réu** — Reu/passivo
3. **Autor específico** —Nome do autor (ex: "MARIA SILVA")
4. **Réu específico** —Nome do réu (ex: "JOão DA SILVA")
5. **Todos** — Tanto autor quanto réu

### Como Funciona Hoje via `polo_prazo`

| `polo_prazo` | Resultado na Certidão |
|--------------|----------------------|
| `autor` | "à parte autora MARIA SILVA" |
| `reu` | "ao réu JOÃO DA SILVA" |
| `ambos` | "aos autores e réus" |
| (vazio) | "à(s) parte(s)" (genérico) |

### Exemplo Prático de Observação com Placeholder

**Template atual** (linha 1369 do `cumprimento_service.py`):
```python
'parte': CumprimentoService._rotulo_parte(
    self._papel_resolvido(record), record.parte_nome),
```

**Gera textos como:**
- DJEN + autor: `"Intimação eletrônica (DJEN) — Prazo de 15 dias úteis à parte autora MARIA. Leitura em 09/02/2026; não contam a leitura nem o 1º dia útil subsequente à leitura; início da contagem em 11/02/2026; término em 03/03/2026 (decorrido o prazo em 04/03/2026)."`
- Advogado + réu: `"Intimação ao advogado — Prazo de 10 dias uteis ao réu JOSE. Leitura em 09/02/2026; o dia da leitura não conta; início da contagem em 10/02/2026; término em 23/02/2026 (decorrido o prazo em 24/02/2026)."`

### Como Configurar para Incluir o Nome

No RAGExample sequência:

```json
{
  "polo_prazo": "autor_especifico",  // Ou 'reu_especifico'
  ...
}
```

O sistema então usa `record.parte_nome` (nome da parte do processo real) ao invés de rótulo genérico.

## Próximos Passos

1. **Adicionar flag `informar_decursao`** no RAGExample para controlar se a certidão informa se o prazo decorreu ou não
2. **Configurar `polo_prazo`** nas RAGs ativas conforme o destinatário desejado (autor, reu, ambos, ou nomes específicos)
3. **Testar o fluxo** com um processo real para validar a observação e certidão geradas

## Referências

- `projudi/prazo_service.py` — Contagem de prazos e cálculo de dados_decurso
- `projudi/cumprimento_service.py` — Métodos `_config_prazo_do_rag`, `_rotulo_parte`, `_html_certidao_prazo`
- RAG 2525 exemplo: `polo_prazo=reu`, `observacao_prazo=True`