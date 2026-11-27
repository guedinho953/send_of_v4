# Manual de implementação no outro PC — certidões

> Atualização: 2026-11-27
> Branch de referência: **`feature/fila-peticoes-acoes`**
> Último commit antes deste manual: **`7506672`**
> Repositório: `https://github.com/guedinho953/send_of_v4`

## 1. Leia primeiro: os dois projetos divergiram

O outro PC tem o **módulo novo de certidões** no `master` (filas de
petições/movimentações, RAG, juntar/intimar, decurso etc.), com histórico
próprio. A branch deste PC foi criada a partir de outra base e tem uma
implementação **paralela** do módulo de certidões.

Consequências:

- **Não faça merge cego** da branch no `master` do outro PC.
- **Não copie as migrations com a mesma numeração**: as duas linhas usam
  números diferentes para coisas diferentes.
- O caminho recomendado é **portar funcionalidade por funcionalidade**,
  usando esta branch como referência e preservando o módulo novo do outro PC.

### Numeração de migrations

| App | Neste PC (branch) | No outro PC (`origin/master`) | O que fazer |
|-----|-------------------|-------------------------------|-------------|
| `projudi` | `0018` e `0019` | já tem `0019` (e anteriores) | criar novas migrations a partir de **`0020`** |
| `processes` | `0024` a `0029` | já tem `0020` a `0031` | criar novas migrations a partir de **`0032`** |

Nunca copie `projudi/0018*`, `projudi/0019*` nem `processes/0024*`–`0029*`
para o outro PC. Use o conteúdo delas como referência e crie migrations
novas depois da última de lá.

## 2. Como puxar o código

No outro PC, com a árvore limpa (commit ou stash antes):

```powershell
git fetch origin
git branch -r
git switch -c integracao-certidoes feature/fila-peticoes-acoes
```

Se preferir trabalhar em um worktree separado:

```powershell
git worktree add ..\send_of_v4_certidoes feature/fila-peticoes-acoes
```

Para ver só o que mudou nas certidões:

```powershell
git diff --stat origin/master..feature/fila-peticoes-acoes
git diff origin/master..feature/fila-peticoes-acoes -- projudi processes templates
```

### Alternativa sem acesso ao remoto

Neste PC:

```powershell
git bundle create ..\send_of_v4_certidoes.bundle feature/fila-peticoes-acoes
```

No outro PC:

```powershell
git fetch ..\send_of_v4_certidoes.bundle feature/fila-peticoes-acoes
git switch -c integracao-certidoes FETCH_HEAD
```

## 3. Antes de alterar

1. Pare o servidor.
2. Faça backup do PostgreSQL principal (`pg_send_of`) e do código.
3. Trabalhe em branch separada.
4. **Não altere** `.env`, `DATABASES`, portas ou o nome do banco.
5. **Não copie** `db.sqlite3`, `var/`, `media/`, `pgdata/`, cookies ou
   `.env` deste PC.

## 4. O que a branch entrega

| Recurso | Arquivos principais | Observação |
|---------|---------------------|------------|
| Separação petições × movimentações | `projudi/models.py` (campos `origem`, `peticao_documento`, `peticao_url`), `projudi/certidao_views.py`, `templates/projudi/certidao_dashboard.html` | No outro PC, adaptar ao dashboard/modelos existentes; criar migration nova (`projudi/0020+`) |
| Contagem DJEN corrigida | `projudi/prazo_service.py`, `test_prazo_djen.py` | Publicação = 1º dia útil seguinte à disponibilização, sem deslocar a disponibilização |
| Decurso 15 dias | `projudi/decurso_pagamento_service.py`, `projudi/decurso_certidao.py`, `projudi/decurso_views.py`, comando `certidao_decurso_pagamento`, template | Usar como referência para o decurso do outro PC; nova migration de template depois de `0031` |
| Texto do decurso com evento | `processes/0027...`, `processes/0029...` | Evento da intimação sempre no texto; cabeçalho de parte só se houver nome |
| Fila de petições com escolha manual | `projudi/peticoes_inominado.py`, `projudi/peticoes_views.py`, `templates/projudi/certidao_peticoes_fila.html` | O outro PC já tem fila; portar apenas a escolha manual/validações que faltarem, sem duplicar views/modelos |
| Intimação por evento | `projudi/intimacao_service.py` | Reutilizar/adaptar ao serviço de intimação existente |
| Modelo base de prazo | `projudi/management/commands/prazo_djen.py` (`_texto_publico_prazo`), `processes/0028...` | Contrarrazões/impugnação; recurso inominado continua no COJE |
| Contrarrazões com tempestividade | `_texto_publico_prazo` | Texto público conclui TEMPESTIVIDADE/INTEMPESTIVIDADE e cita o evento do recurso |
| Recorrente na linha `PARA` | `projudi/partes_inominado.py`, `projudi/management/commands/certidao_inominado.py` | Reforço por rótulos e trechos “já devidamente qualificado”, “nos autos”, “vem interpor” |
| Juntar/intimar | `projudi/juntar_service.py`, `projudi/juntar_views.py`, `templates/projudi/certidao_juntar_intimar.html` | O outro PC já tem o fluxo completo; usar como referência, não duplicar |
| Senha da assinatura | `accounts_user.projudi_password` | Campo no Admin em **Usuários → Projudi → Senha da assinatura**; vazio = assinatura manual |
| Log assíncrono do Playwright | `core/settings.py` | Adicionar `DJANGO_ALLOW_ASYNC_UNSAFE=1` |

## 5. Ordem recomendada de implementação

### Etapa 1 — baixo risco, sem tocar no fluxo de juntada

1. **Contagem DJEN**
   - Portar a correção de `projudi/prazo_service.py` (`contar_prazo_djen`).
   - Atualizar os testes de sábado/domingo/Finados.
2. **Texto/template do decurso**
   - Adaptar o decurso existente do outro PC para:
     - `Certifico, para os devidos fins, o DECURSO DO PRAZO...`;
     - evento da intimação sempre no texto;
     - publicação, início e decurso;
     - assinatura `IVAN GUEDES DA SILVA / Servidor Secretaria 2`.
   - Criar uma migration de **dados** depois da `processes/0031` para atualizar
     o `DocumentTemplate` (não copiar `processes/0024`–`0029`).
3. **Cabeçalho de partes**
   - `EXECUTADO(A)`/`PARTE` só aparecem se houver nome.
4. **Recorrente no `PARA`**
   - Adaptar a linha `PARA` para `Recorrente: NOME`.
   - Reforçar a identificação no PDF (rótulos + expressões do cabeçalho).

### Etapa 2 — contrarrazões e modelo base

1. Portar `_texto_publico_prazo` para o gerador de certidões do outro PC.
2. Contrarrazões:
   - texto público conclui **TEMPESTIVIDADE** ou **INTEMPESTIVIDADE**;
   - cita o evento do recurso inominado;
   - datas de publicação/início/termo final.
3. Impugnação/cumprimento/penhora:
   - texto público com prazo, evento da intimação e termo final;
   - protocolo/tempestividade na memória interna.
4. Recurso inominado:
   - **não alterar** o modelo COJE; apenas a linha `PARA` do recorrente.

### Etapa 3 — juntar/intimar

O outro PC já tem `CertidaoPeticaoJuntarIntimarView` e o
`MovimentacaoService` com `executar_requests`/`executar_com_intimacao`.
Não duplique o fluxo. Ajustes recomendados:

1. Adicionar/confirmar `DJANGO_ALLOW_ASYNC_UNSAFE=1` no `settings.py` para
   evitar o erro falso de log assíncrono depois da assinatura.
2. Conferir o campo `User.projudi_password` e o Admin.
3. Manter a assinatura manual quando a senha estiver vazia; preencher
   automaticamente quando estiver salva.
4. Bloquear juntada duplicada: verificar se já existe `MovimentacaoRecord`
   com o mesmo processo/título e status `cumprido`.
5. Intimação: manter as regras do módulo novo:
   - tempestivo/gratuidade → recorrido, contrarrazões, 10 dias;
   - intempestivo → recorrente, ciência, 5 dias;
   - polo e prazo ajustáveis.

## 6. Migrations: como criar no outro PC

### 6.1 Campos em `PrazoDjenRecord` (se o outro PC usar esse modelo)

Se o modelo existir no outro PC, criar uma migration nova em `projudi`
(primeira disponível depois da última de lá, ex.: `0020`):

```python
# projudi/migrations/0020_prazodjenrecord_campos_certidoes.py
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('projudi', '0019_ultima_migration_do_outro_pc'),
    ]

    operations = [
        migrations.AddField(
            model_name='prazodjenrecord',
            name='origem',
            field=models.CharField(
                choices=[('peticao', 'Petição'),
                         ('movimentacao', 'Movimentação')],
                db_index=True, default='movimentacao',
                max_length=20, verbose_name='Origem'),
        ),
        migrations.AddField(
            model_name='prazodjenrecord',
            name='peticao_documento',
            field=models.CharField(
                blank=True, max_length=300,
                verbose_name='Documento da petição'),
        ),
        migrations.AddField(
            model_name='prazodjenrecord',
            name='peticao_url',
            field=models.URLField(
                blank=True, max_length=500, verbose_name='URL da petição'),
        ),
        migrations.AddField(
            model_name='prazodjenrecord',
            name='evento_origem',
            field=models.CharField(
                blank=True, max_length=20,
                verbose_name='Evento de origem'),
        ),
    ]
```

> Se o outro PC usa `CumprimentoRecord`/`MovimentacaoRecord` em vez de
> `PrazoDjenRecord`, adapte os campos para o modelo dele; não crie um modelo
> paralelo.

### 6.2 Template do decurso

Criar uma migration **de dados** depois da `processes/0031` (ex.: `0032`)
que atualiza o `DocumentTemplate` existente. Use como referência:

- `processes/0027_certidao_decurso_evento_intimacao.py`;
- `processes/0029_cabecalho_partes_condicional.py`.

O template final deve conter:

```django
{% if executado %}<strong>EXECUTADO(A)</strong> - {{ executado }}<br>{% endif %}
...
referente à <strong>intimação eletrônica (DJEN)</strong>{% if evento_intimacao and evento_intimacao != 'manual' %}, evento {{ evento_intimacao }}{% else %}, evento não informado{% endif %}.
Publicação em {{ data_publicacao }}; início do prazo em {{ data_inicio_contagem }}; decurso em {{ ultimo_dia }}.
...
<strong>{{ servidor|upper }}</strong><br>
{{ servidor_cargo }}<br>
Documento Assinado Eletronicamente<sup>1</sup>
```

### 6.3 Modelo base de prazo

Criar uma migration de dados depois da anterior (ex.: `0033`) com o template
`Certidão de Prazo — Modelo Base` (referência:
`processes/0028_certidao_prazo_modelo_base.py`). O corpo usa
`{{ texto_certidao|safe }}`, o evento e o subscritor.

## 7. Testes no outro PC

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test projudi
```

Testes de referência desta branch:

```powershell
.\.venv\Scripts\python.exe -m unittest test_prazo_djen test_verificacao_inominado test_peticoes_inominado test_partes_inominado test_intimacao_evento
.\.venv\Scripts\python.exe manage.py test test_certidao_origem test_decurso_pagamento test_peticoes_fila_views test_juntar_intimar
```

## 8. Senha da assinatura

- **Tabela:** `accounts_user`
- **Coluna:** `projudi_password`
- **Admin:** `/admin/accounts/user/<id>/change/` → **Projudi → Senha da
  assinatura**.
- **Shell:**
  ```python
  from django.contrib.auth import get_user_model
  u = get_user_model().objects.get(email='USUARIO')
  u.projudi_password = 'SENHA'
  u.save(update_fields=['projudi_password'])
  ```
- Vazia: o fluxo tenta a assinatura salva no Projudi e, se aparecer o campo
  de senha, **aguarda a assinatura manual** no navegador.
- Preenchida: preenche automaticamente.
- O campo é texto simples no banco; proteja Admin/banco e não compartilhe a
  senha em chats/logs.

## 9. Checklist

- [ ] Branch/worktree criado no outro PC.
- [ ] Backup do `pg_send_of` e do código.
- [ ] `DJANGO_ALLOW_ASYNC_UNSAFE=1` no `settings.py`.
- [ ] Migrations novas criadas depois das últimas do outro PC (não copiar
      `projudi/0018-0019` nem `processes/0024-0029`).
- [ ] Contagem DJEN corrigida.
- [ ] Decurso com texto/evento/assinatura revisados.
- [ ] Cabeçalho de parte condicional.
- [ ] `PARA` do inominado com o recorrente.
- [ ] Contrarrazões com TEMPESTIVIDADE/INTEMPESTIVIDADE.
- [ ] Modelo base de impugnação/cumprimento.
- [ ] Juntar/intimar do outro PC revisado (não duplicar).
- [ ] Senha da assinatura configurada (ou manual assumido).
- [ ] `manage.py check` e testes passando.
- [ ] Preview e um teste controlado antes de liberar.

## 10. O que não fazer

- Não copiar `.env`, `db.sqlite3`, `var/`, `media/`, `pgdata/`.
- Não alterar `DATABASES`/`pg_send_of`.
- Não copiar migrations com números já usados no outro PC.
- Não substituir o módulo novo de certidões pelo módulo paralelo desta
  branch sem uma decisão explícita.
- Não executar juntada/intimação em processo real sem conferir o plano.
