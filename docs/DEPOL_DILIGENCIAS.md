# Ofício DEPOL — Cumprimento de Diligências

## O que faz

Monta o ofício à **DEPOL — Delegacia de Polícia de Paulo Afonso** a partir de:

1. **último despacho do juiz** com documento (texto integral);
2. **parecer/manifestação do Ministério Público** referenciado nesse despacho
   (pelo número do evento) ou, na falta da referência, o último parecer com
   documento.

O sistema extrai a lista numerada de diligências do parecer e monta duas
variações:

| Despacho | Ofício |
|----------|--------|
| “encaminhando cópia”, “com cópia”, “cópia do requerido” | **Com cópia**: transcreve o parecer integral do MP, indicando o evento |
| “sem cópia” ou sem menção a cópia | **Sem cópia**: lista apenas as diligências, no corpo do ofício |

Réus e autores do fato não entram na lista; a lista vem do parecer do MP.
As diligências endereçadas a outros órgãos (ex.: Secretaria de Meio Ambiente)
são separadas das diligências da autoridade policial.

## Destinatário fixo

```
DEPOL — Delegacia de Polícia de Paulo Afonso
Rodovia BA 210, S/N — BTN I
48.600-000 — Paulo Afonso/BA
E-mail: dt.pauloafonso@pcivil.ba.gov.br
```

## Preview (não expede)

```bat
.venv\Scripts\python.exe manage.py preview_oficio_depol --processo 0002803-76.2025.8.05.0191
.venv\Scripts\python.exe manage.py preview_oficio_depol --processo 0002803-76.2025.8.05.0191 --sem-copia
.venv\Scripts\python.exe manage.py preview_oficio_depol --processo 0002803-76.2025.8.05.0191 --com-copia
```

O HTML é salvo em `var/preview_depol_<processo>.html`. Abra no Firefox para
revisar.

## Expedir pela interface

No dashboard de Ofícios, em **⚡ Expedir ofícios**, escolha:

```
DEPOL — Cumprimento de Diligências (MP)
```

O sistema detecta automaticamente o despacho e o parecer do MP. Se a planilha
Google estiver disponível, usa o número dela; caso contrário, usa o maior
número do sistema + 1 (`140/2026` no banco atual).

## Limitações

- Se o parecer do MP não tiver lista numerada ou não tiver documento, o
  ofício não é montado e o motivo aparece no log.
- PDFs são lidos com `pymupdf` (já incluído em `requirements-windows.txt`).
- O parecer citado no despacho é localizado pelo número do evento; se o
  despacho não citar, usa o parecer mais recente com documento.
- O texto do parecer integral é transcrito no corpo do ofício; não há anexo
  PDF separado.
