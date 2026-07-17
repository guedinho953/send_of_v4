# 📨 03 — Processar Pendentes com Impossibilidade Humanizada

## Data: 2026-07-17

---

## Visão Geral

Botão **📨 Processar Pendentes** no dashboard de ofícios (`/projudi/oficios/dashboard/`).

**O que faz:** Para cada ofício com status `pendente` ou `falhou_email`:
1. Tenta enviar e-mail
2. Se enviar → juntada normal (Cumprimento de Ofício)
3. Se **NÃO** enviar → juntada de impossibilidade no Projudi com o motivo
4. Se a juntada no Projudi falhar → registra localmente o motivo

---

## Arquivos Modificados

| Arquivo | Linhas | O que foi alterado |
|---------|--------|-------------------|
| `projudi/oficio_views.py` | 260-326 | Nova view `OficioProcessarPendentesView` |
| `projudi/oficio_service.py` | 594-645 | `processar_oficio()` melhorado |
| `projudi/oficio_service.py` | 713-742 | `humanizar_erro()` — nova mensagem "sem email" |
| `projudi/oficio_service.py` | 580-589 | `_gerar_texto_impossibilidade()` |
| `projudi/urls.py` | 23 | Nova rota `oficios/processar-pendentes/` |
| `templates/projudi/oficio_dashboard.html` | 111-116 | Botão "📨 Processar Pendentes" |

---

## Fluxo Completo

```
[📨 Processar Pendentes]
         │
         ▼
  OficioProcessarPendentesView.post(request)
         │
         ├── Filtra: status IN ('pendente', 'falhou_email')
         │
         ├── Para cada ofício:
         │       │
         │       ▼
         │   service.processar_oficio(record)
         │       │
         │       ├── 1. Tenta enviar e-mail
         │       │       ├── ✅ Sucesso → status='enviado'
         │       │       │               → juntar_cumprimento()
         │       │       │               → retorna {'enviado': True}
         │       │       │
         │       │       └── ❌ Falha  → motivo = humanizar_erro(erro_técnico)
         │       │                       → tenta juntar_resposta_impossibilidade()
         │       │
         │       └── 2. Tenta juntar impossibilidade no Projudi
         │               ├── ✅ Sucesso → status='juntado'
         │               │               retorna {'juntado': True, 'enviado': False}
         │               │
         │               └── ❌ Falha  → salva observacao_retorno local
         │                               retorna {'enviado': False, 'juntado': False}
         │
         └── Mostra resultado no dashboard:
              ├── ✅ X ofício(s) enviado(s) e juntado(s)
              ├── 📋 Y ofício(s) juntado(s) com impossibilidade no Projudi
              └── 📝 Z ofício(s) com impossibilidade registrada localmente
```

---

## View: `OficioProcessarPendentesView`

**Arquivo:** `projudi/oficio_views.py:260`

```python
class OficioProcessarPendentesView(LoginRequiredMixin, View):
    """
    POST /projudi/oficios/processar-pendentes/
    """
    def post(self, request):
        pendentes = OficioRecord.objects.filter(
            user=request.user,
            status__in=['pendente', 'falhou_email']
        )
        # ...
        for record in pendentes:
            resultado = service.processar_oficio(record)
            if resultado.get('enviado'):
                enviados += 1
            elif resultado.get('juntado'):
                impossibilidade_juntada += 1
            else:
                impossibilidade_local += 1
```

**Contadores:**

| Variável | Significado |
|----------|-------------|
| `enviados` | Email enviou + juntada normal |
| `impossibilidade_juntada` | Email falhou, mas impossibilidade foi pro Projudi |
| `impossibilidade_local` | Email falhou + impossibilidade NÃO foi pro Projudi |
| `erros` | Exceção durante o processamento |

---

## Service: `processar_oficio()`

**Arquivo:** `projudi/oficio_service.py:594`

```python
def processar_oficio(self, record):
    resultado = {'enviado': False, 'juntado': False, 'erro': None}

    # Pula se já juntado
    if record.juntado:
        return resultado

    # 1) Tenta enviar e-mail
    ok_envio, info = self.enviar_email(record)
    if ok_envio:
        resultado['enviado'] = True
        resultado['juntado'] = self.juntar_cumprimento(record)
    else:
        resultado['erro'] = info
        motivo_humanizado = self.humanizar_erro(info)

        # 2) Tenta juntada de impossibilidade
        try:
            ok = self.juntar_resposta_impossibilidade(record, motivo=motivo_humanizado)
            if ok:
                resultado['juntado'] = True
            else:
                # 3) Fallback: registra localmente
                observacao = (
                    f"Não foi possível enviar o Ofício {record.numero_oficio} ...\n"
                    f"Motivo: {motivo_humanizado}\n"
                    f"A juntada no Projudi não pôde ser concluída..."
                )
                record.observacao_retorno = observacao
                record.save()
        except Exception as e:
            self._log(record, 'erro_juntada', str(e)[:100])

    return resultado
```

---

## Humanização de Erros

**Arquivo:** `projudi/oficio_service.py:713`

```python
def humanizar_erro(self, erro: str) -> str:
```

Tabela de tradução:

| Erro técnico | Mensagem humanizada |
|-------------|-------------------|
| `nenhum e-mail de destino` | "o ofício não possui e-mail de destinatário." |
| `jsessionid`, `sessao`, `expirada` | "A sessão do Projudi expirou..." |
| `smtp`, `email`, `gmail` | "Verifique se a senha de app do Gmail..." |
| `timeout`, `connection`, `conexao` | "Conexão com o Projudi está lenta..." |
| `not found`, `404` | "Página do ofício não encontrada..." |
| `juntada`, `cumprimento` | "Não foi possível registrar a juntada..." |
| (outros) | "Ocorreu um problema inesperado: ..." |

**Novo caso adicionado hoje:**
```python
if 'nenhum e-mail' in erro or 'email de destino' in erro or 'sem email' in erro:
    return "o ofício não possui e-mail de destinatário."
```

---

## Texto de Impossibilidade

**Arquivo:** `projudi/oficio_service.py:580`

```python
def _gerar_texto_impossibilidade(self, record, motivo=""):
    motivo_final = motivo or "e-mail de destinatário ausente ou inválido"
    texto = (
        f"Impossibilidade de cumprimento do Ofício n {record.numero_oficio}, "
        f"processo {record.numero_processo_cnj or record.processo}. "
        f"Motivo: {motivo_final}. "
        f"Foi tentado o envio automático em {datetime.now()...} sem êxito. "
        f"Aguarda providências do Cartório para novo encaminhamento."
    )
    return texto
```

**Exemplo de saída:**
> Impossibilidade de cumprimento do Ofício n 066/2026, processo 41020252141214. Motivo: o ofício não possui e-mail de destinatário. Foi tentado o envio automático em 17/07/2026 18:30 sem êxito. Aguarda providências do Cartório para novo encaminhamento.

---

## Botão no Dashboard

**Arquivo:** `templates/projudi/oficio_dashboard.html:111`

```html
<form method="post" action="{% url 'projudi:oficio_processar_pendentes' %}">
    {% csrf_token %}
    <button type="submit" class="btn"
        style="background:linear-gradient(135deg,#7c3aed,#a855f7); color:white;
               font-weight:600; box-shadow:0 2px 8px rgba(124,58,237,0.4);">
        📨 Processar Pendentes
    </button>
</form>
```

Aparece **apenas quando há pendentes** (dentro do `{% if pendentes > 0 %}`).

---

## Rota

**Arquivo:** `projudi/urls.py:23`

```python
path('oficios/processar-pendentes/',
     oficio_views.OficioProcessarPendentesView.as_view(),
     name='oficio_processar_pendentes'),
```

---

## Mensagens no Dashboard

| Condição | Ícone | Nível |
|----------|-------|-------|
| Algum ofício enviado | ✅ | success |
| Algum ofício juntado com impossibilidade | 📋 | warning |
| Algum ofício com impossibilidade local | 📝 | warning |
| Algum erro de exceção | ❌ | error |
| Nenhum pendente | — | info |
