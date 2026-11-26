# Certidão de Prazo — nome do recorrente

A Certidão de Prazo agora exibe o campo **RECORRENTE** na tabela e no corpo.

## Origem do nome

1. `CumprimentoRecord.parte_nome`, quando já preenchido pelo fluxo;
2. se estiver vazio, busca no cadastro do processo:
   - polo autor/promovente/exequente;
   - polo réu/executado/promovido;
   - ambos, quando o papel for `ambos`.

Função: `CumprimentoService._nome_recorrente`.

## Template

`DocumentTemplate` **Certidão de Prazo** (id 11), variável:

```django
{{ recorrente }}
```

A migração `0020_certidao_prazo_recorrente` atualiza o template existente.
`criar_template_certidao_prazo.py` também foi atualizado para novas instalações.

## Fallback

Se não for possível resolver o nome, o campo fica vazio e o corpo da certidão
continua sendo gerado normalmente.
