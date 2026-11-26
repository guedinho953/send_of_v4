# Manual — Intimação do recorrente e partes na certidão

> Atualização: 2026-11-26
> Aplica-se ao projeto `send_of_v4` no Windows (e também no Linux/portátil).
> **Não altera** a configuração de banco do outro PC: o PostgreSQL
> `pg_send_of` continua sendo o principal e o SQLite, o espelho.

---

## 1. Objetivo

A certidão de recurso inominado deve apurar a tempestividade pela
**intimação do recorrente**, e não por qualquer DJEN do processo.

Exemplo real (0002888-28.2026.8.05.0191):

- o recurso é do **BANCO BRADESCO S.A.**;
- o processo tem DJEN para a Maria (evento 48) e para o Bradesco
  (evento 49), ambos em 09/11/2026;
- a intimação correta é a **do Bradesco (evento 49)**, pois é ele quem
  recorreu.

Além disso, a linha `PARA` da certidão passa a mostrar:

```
Promovente: MARIA DE FATIMA DE JESUS / Promovido: BANCO BRADESCO S A
```

Se as partes não forem localizadas, a linha `PARA` é **omitida** (não
aparece mais “as partes”).

---

## 2. O que mudou

1. O sistema identifica o **recorrente**:
   - pelo texto do PDF da petição (rótulos `RECORRENTE`, `AGRAVANTE`,
     `APELANTE` etc.; ou pela primeira parte citada na petição);
   - ou pelo parâmetro `--recorrente "NOME"`, quando o PDF é digitalizado
     ou a identificação automática falhar.
2. O DJEN é filtrado pelo nome do recorrente:
   - entre os DJENs anteriores ao recurso, dá preferência ao que cita
     nominalmente o recorrente;
   - se nenhum citar, usa o mais recente e emite aviso para conferência.
3. A linha `PARA` da certidão:
   - mostra `Promovente: ... / Promovido: ...`;
   - é omitida quando não há partes;
   - pode ser sobrescrita com `--parte "..."`.
4. O comando da fila `JuntadaPeticao` passa automaticamente o PDF da
   petição para a identificação do recorrente.
5. Nada é juntado/movimentado no Projudi. O fluxo é somente leitura +
   preview + registro no dashboard.

---

## 3. Arquivos alterados/criados

| Arquivo | O que faz |
|---------|-----------|
| `projudi/partes_inominado.py` | **Novo.** Lê partes, limpa nomes, identifica o recorrente e baixa o texto do PDF. |
| `projudi/verificacao_inominado.py` | `achar_intimacao_djen(..., parte=...)` prefere o DJEN nominal do recorrente. |
| `projudi/management/commands/certidao_inominado.py` | Novas opções `--recorrente` e `--peticao-url`; imprime partes/recorrente; passa as partes para a certidão. |
| `projudi/management/commands/peticoes_inominado.py` | Passa o PDF da fila e o recorrente para o comando de certidão. |
| `projudi/management/commands/prazo_djen.py` | Linha `PARA` vazia quando não há partes; fallback HTML condicional. |
| `processes/migrations/0023_certidao_recurso_inominado_partes.py` | **Novo.** Torna a linha `PARA` condicional no template COJE. |
| `test_partes_inominado.py` | **Novo.** Testes de partes/recorrente/DJEN nominal. |
| `test_peticoes_inominado.py` | Já existente; continua cobrindo a fila. |
| `test_verificacao_inominado.py` | Já existente; continua cobrindo DJEN/data-limite. |
| `docs/PRAZO_DJEN.md` | Documentação das novas opções e regra. |

> A correção do parser de datas (`25/11/2026` com 4 dígitos) veio na
> atualização anterior da fila. Se o outro PC ainda não tiver essa
> atualização, ela também é necessária.

---

## 4. Antes de começar

No outro PC:

1. **Pare** a aplicação (servidor Django) para evitar gravação durante a
   atualização.
2. Faça **backup** do banco principal (`pg_send_of`) e do projeto.
3. Anote o caminho do projeto. Nos exemplos abaixo:
   - Windows: `C:\send_of_v4`
   - ajuste conforme o seu caso.
4. Confirme que o `.venv` está ativo ou use o caminho completo:
   ```powershell
   .\.venv\Scripts\python.exe manage.py check
   ```

**Não copie** do outro PC para este (nem deste para o outro):

- `.env`
- `db.sqlite3`
- `pgdata\` (se houver)
- `var\`
- `media\`
- cookies/sessões

Esses arquivos são específicos de cada instalação.

---

## 5. Atualizar o código

### Opção A — copiar os arquivos (recomendado se não houver git remoto)

1. No PC atual, compacte apenas os arquivos da seção 3, preservando as
   pastas. Exemplo no PowerShell:

   ```powershell
   Compress-Archive -Force -DestinationPath "$env:TEMP\recorrente_partes.zip" `
     -Path projudi\partes_inominado.py,`
           projudi\verificacao_inominado.py,`
           projudi\management\commands\certidao_inominado.py,`
           projudi\management\commands\peticoes_inominado.py,`
           projudi\management\commands\prazo_djen.py,`
           processes\migrations\0023_certidao_recurso_inominado_partes.py,`
           test_partes_inominado.py,`
           docs\PRAZO_DJEN.md
   ```

2. Copie o ZIP para o outro PC e extraia **na raiz do projeto**,
   substituindo os arquivos existentes.
3. Confira se os arquivos ficaram nos caminhos corretos:
   ```powershell
   Test-Path projudi\partes_inominado.py
   Test-Path processes\migrations\0023_certidao_recurso_inominado_partes.py
   ```

### Opção B — git

Se o outro PC compartilha o mesmo repositório:

```powershell
git status
git pull
```

Se o repositório não tem remoto, gere um pacote no PC atual:

```powershell
git bundle create ..\send_of_v4_recorrente.bundle master
```

No outro PC:

```powershell
git fetch ..\send_of_v4_recorrente.bundle master
git merge FETCH_HEAD
```

---

## 6. Dependências

Não há dependência nova. A leitura do PDF usa o `pymupdf` (já instalado
para a fila de petições). Se o outro PC não tiver:

```powershell
.\.venv\Scripts\python.exe -m pip install pymupdf
```

---

## 7. Migrações

A mudança **não cria campos novos**. A única migração é de dados: ela
torna a linha `PARA` condicional no template
`Certidão de Recurso Inominado (COJE)`.

No outro PC:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Saída esperada (entre outras):

```
Applying processes.0023_certidao_recurso_inominado_partes... OK
```

Confira o template:

```powershell
.\.venv\Scripts\python.exe manage.py shell
```

```python
from processes.models import DocumentTemplate
tpl = DocumentTemplate.objects.get(name='Certidão de Recurso Inominado (COJE)')
print('{% if parte %}' in tpl.html_template)
```

Deve imprimir `True`.

> Se o template não existir, aplique primeiro a migração `processes/0022`
> (o `migrate` já faz isso) ou crie/atualize o template no admin.

### PostgreSQL principal

Rode o `migrate` com a configuração atual do outro PC. **Não altere**
`DATABASES`, `.env` nem a porta do `pg_send_of`. A migração apenas
atualiza o registro do template na tabela `processes_documenttemplate`.

Se o projeto também mantém um SQLite espelho, repita a migração no
ambiente que aponta para o espelho (mesmo comando `migrate`, com a
configuração do espelho). Não copie o `db.sqlite3` deste PC.

---

## 8. Conferir a sessão do Projudi

A leitura da fila e do processo usa o `JSESSIONID`.

1. Abra o sistema e sincronize a sessão em `/projudi/sessao/`.
2. Teste:
   ```powershell
   .\.venv\Scripts\python.exe manage.py peticoes_inominado --listar
   ```
3. Se aparecer “Sessão do Projudi expirada”, sincronize novamente.

---

## 9. Teste 1 — listar a fila

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado --listar
```

Saída esperada (a fila muda com o tempo):

```
Recursos inominados na fila: 3

1) 0002888-28.2026.8.05.0191 — 25/11/2026
   Tipo......: Juntada de Petição de Recurso Inominado
   Detecção..: tipo da juntada
   Petição...: 0002888-28.2026.8.05.0191 - ri.pdf
   Comprovantes/guias (conferir manualmente):
     - 77307.0-1-COMPROVANTES.pdf
   Processo..: https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso?...
```

- O comando **não** executa “Movimentar / Juntar”.
- Os comprovantes são apenas listados; **você** confere o preparo.

Se a fila não mostrar um recurso que deveria aparecer:

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado --listar --verificar-pdf
```

O `--verificar-pdf` baixa a petição e procura “RECURSO INOMINADO” no
texto, para casos em que o tipo/nome do PDF não identificam.

---

## 10. Teste 2 — preview sem gravar no dashboard

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado ^
  --processo 0002888-28.2026.8.05.0191 ^
  --preparo completo ^
  --nao-registrar ^
  --saida "var\teste_0002888.html"
```

Saída esperada (trechos):

```
Partes...: Promovente: MARIA DE FATIMA DE JESUS / Promovido: BANCO BRADESCO S A
Recurso..: evento 55 — Juntada de Petição de Recurso Inominado — protocolo 2026-11-25
Recorrente: BANCO BRADESCO S A (identificado na petição PDF)
Intimação: evento 49 — Disponibilização ... em (09/11/26) ...
           disponibilização 09/11/2026 (DJEN; recorrente BANCO BRADESCO S A)
...
Tempestividade ...........: TEMPESTIVO
Último dia ...............: 25/11/2026
```

Confira no HTML:

```powershell
Select-String -Path var\teste_0002888.html -Pattern "PARA|Promovente|Promovido"
```

Deve aparecer:

```html
<tr><td><strong>PARA</strong></td><td>-</td>
<td>Promovente: MARIA DE FATIMA DE JESUS / Promovido: BANCO BRADESCO S A</td></tr>
```

Se preferir não gerar o HTML:

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado ^
  --processo 0002888-28.2026.8.05.0191 --preparo completo ^
  --nao-registrar --sem-html
```

---

## 11. Se a detecção automática falhar

### 11.1 O recurso ainda não virou evento no processo

Use a data de envio da fila:

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado ^
  --processo 0002888-28.2026.8.05.0191 ^
  --preparo completo ^
  --data-protocolo 25/11/2026
```

O evento da certidão fica `infra`.

### 11.2 O PDF não tem texto (digitalizado) ou o recorrente não foi achado

Informe manualmente:

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado ^
  --processo 0002888-28.2026.8.05.0191 ^
  --preparo completo ^
  --recorrente "BANCO BRADESCO S A"
```

Se o PDF nem estiver na fila, passe a URL dele:

```powershell
--peticao-url "https://projudi.tjba.jus.br/projudi/listagens/DownloadArquivo?arquivo=210452838"
```

### 11.3 O DJEN correto não foi escolhido

Confira o evento e a data nos autos e informe:

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado ^
  --processo 0002888-28.2026.8.05.0191 ^
  --preparo completo ^
  --recorrente "BANCO BRADESCO S A" ^
  --data-disponibilizacao 09/11/2026 ^
  --evento-intimacao 49
```

### 11.4 As partes não apareceram

Use `--parte` com o texto que deve ir na linha `PARA`:

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado ^
  --processo 0002888-28.2026.8.05.0191 ^
  --preparo completo ^
  --parte "Promovente: MARIA DE FATIMA DE JESUS / Promovido: BANCO BRADESCO S A"
```

Se quiser **omitir** a linha `PARA`, deixe `--parte` de fora e não passe
partes. A migração `0023` já deixa a linha condicional.

---

## 12. Gerar a certidão final

Sem `--nao-registrar`, o controle é gravado no dashboard:

```powershell
.\.venv\Scripts\python.exe manage.py peticoes_inominado ^
  --processo 0002888-28.2026.8.05.0191 ^
  --preparo completo ^
  --saida "var\certidao_0002888_inominado.html"
```

Saída esperada:

```
Preview: ...\var\certidao_0002888_inominado.html
Controle registrado: #N (admin: /admin/projudi/prazodjenrecord/)
```

Abra o dashboard:

```
http://127.0.0.1:8000/projudi/certidoes/
```

Confira:

- **Parte** = `Promovente: MARIA ... / Promovido: BANCO ...`;
- **Preparo** = `Preparo completo`;
- **Status** = `TEMPESTIVO`;
- **Evento do recurso** = 55;
- **Evento da intimação** = 49;
- **Preview** abre o HTML.

---

## 13. Como o sistema decide (para conferência)

1. **Recorrente**
   - procura `RECORRENTE`, `AGRAVANTE`, `APELANTE`, `EMBARGANTE`,
     `IMPETRANTE`, `REQUERENTE` no texto do PDF;
   - se não achar, usa a primeira parte citada no início da petição;
   - se o PDF não tiver texto, use `--recorrente`.
2. **Intimação**
   - considera DJENs anteriores ao evento do recurso e com data efetiva
     até a data do protocolo;
   - entre eles, prefere o que cita o nome do recorrente;
   - se nenhum citar o recorrente, usa o mais recente e avisa.
3. **Partes**
   - lê `Promovente` e `Promovido` da página do processo;
   - limpa rótulos colados ao nome (`Processo(s) Distribuído(s)`, CPF etc.);
   - se não achar, omite a linha `PARA`.
4. **Preparo**
   - **não** é inferido dos comprovantes; use `--preparo`.

---

## 14. Opções novas

| Opção | Onde | Efeito |
|-------|------|--------|
| `--recorrente "NOME"` | `certidao_inominado`, `peticoes_inominado` | Nome do recorrente quando o PDF não permite identificar |
| `--peticao-url URL` | `certidao_inominado`, `peticoes_inominado` | URL do PDF da petição para leitura |
| `--parte "TEXTO"` | `certidao_inominado`, `peticoes_inominado` | Sobrescreve a linha `PARA` |
| `--nao-registrar` | `certidao_inominado`, `peticoes_inominado`, `prazo_djen` | Gera preview sem gravar o controle |
| `--verificar-pdf` | `peticoes_inominado` | Confirma o recurso pelo conteúdo do PDF |

---

## 15. Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---------|----------------|-------------|
| `Sessão do Projudi expirada` | Cookie vencido | Sincronizar em `/projudi/sessao/` |
| `Nenhuma petição de recurso inominado na fila` | Fila vazia, tipo diferente ou nome do PDF ambíguo | Conferir a página `JuntadaPeticao`; testar `--verificar-pdf` |
| `Recorrente não identificado` | PDF digitalizado/sem texto ou nome divergente | Usar `--recorrente "NOME"` |
| `Aviso: a intimação escolhida não cita o recorrente` | DJEN sem o nome da parte | Conferir nos autos; usar `--data-disponibilizacao`/`--evento-intimacao` |
| Linha `PARA` sumiu | Partes não localizadas ou migração 0023 não aplicada | Rodar `migrate`; usar `--parte "..."` |
| Linha `PARA` com “as partes” | Template antigo (migração 0023 não aplicada) | Rodar `migrate`; conferir o template |
| `Data do protocolo não encontrada` | Fila sem `Data Envio` | Usar `--data-protocolo DD/MM/AAAA` |
| `No migrations to apply` | Já migrado | Conferir o template; se necessário, recriar o registro |

---

## 16. PostgreSQL / outro PC

- **Não** altere `DATABASES`, `.env`, portas ou o nome `pg_send_of`.
- Rode `manage.py migrate` no banco principal; a migração 0023 é
  compatível com PostgreSQL e SQLite.
- Se houver banco espelho, rode a mesma migração no ambiente do espelho.
- O portátil (`D:\send_of_v4_portable_win`) usa SQLite; **não** o use como
  banco principal do outro PC. Se quiser atualizar o portátil, rode na
  origem:
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\montar_portatil_windows.ps1 `
    -Destino "D:\send_of_v4_portable_win" -SemNavegador
  ```

---

## 17. Rollback

Se precisar voltar a linha `PARA` antiga:

```powershell
.\.venv\Scripts\python.exe manage.py migrate processes 0022
```

Isso desfaz apenas a alteração do template (a linha volta a
`{{ parte }}`). Os arquivos de código podem ser restaurados do backup.
Não é recomendado desfazer a migração em produção sem necessidade.

---

## 18. Checklist final

- [ ] Arquivos da seção 3 copiados/atualizados.
- [ ] `manage.py check` sem erros.
- [ ] `manage.py migrate` aplicou `processes.0023`.
- [ ] Template contém `{% if parte %}`.
- [ ] `peticoes_inominado --listar` mostra os recursos.
- [ ] Preview do 0002888 mostra partes, recorrente Bradesco e DJEN 49.
- [ ] HTML tem `Promovente: ... / Promovido: ...`.
- [ ] Certidão final registrada no dashboard.
- [ ] Nenhuma ação de “Movimentar/Juntar” foi executada no Projudi.

---

## 19. Resultado esperado no 0002888

```
Partes...: Promovente: MARIA DE FATIMA DE JESUS / Promovido: BANCO BRADESCO S A
Recurso..: evento 55 — Juntada de Petição de Recurso Inominado — protocolo 2026-11-25
Recorrente: BANCO BRADESCO S A (identificado na petição PDF)
Intimação: evento 49 — ... disponibilização 09/11/2026
           (DJEN; recorrente BANCO BRADESCO S A)
Preparo..: completo

Último dia ...............: 25/11/2026
Tempestividade ...........: TEMPESTIVO
```

Texto:

> Certifico, para os devidos fins, conforme as determinações do Ofício
> Circular nº 034/2015/COJE, de 10 de julho de 2015, que o recurso
> inominado interposto no evento 55 afigura-se TEMPESTIVO e regularmente
> PREPARADO. Certifico ainda a regularidade da habilitação dos advogados
> das partes, consoante pedidos realizados até a presente data, nos termos
> do art. 17 do Provimento nº CGJ 03/2010.

Se a petição for de outra parte, o sistema deve escolher o DJEN dela
(ex.: evento 48, da Maria). Se não escolher, use `--recorrente`.
