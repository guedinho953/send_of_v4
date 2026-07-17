# 🎓 04 — Modo Estudante: Explicação Linha por Linha

> Este documento explica CADA LINHA dos códigos implementados no dia 2026-07-17.
> Ideal para quando você quiser estudar e entender profundamente o que foi feito.

---

## 📚 Índice

1. [View: OficioProcessarPendentesView](#1-view-oficioprocessarpendentesview)
2. [Service: processar_oficio()](#2-service-processar_oficio)
3. [Texto de impossibilidade](#3-texto-de-impossibilidade)
4. [Humanização de erros](#4-humanização-de-erros)
5. [Captura de sessão (4 camadas)](#5-captura-de-sessão-4-camadas)
6. [Script de captura de cookies](#6-script-de-captura-de-cookies)
7. [URLs e rotas](#7-urls-e-rotas)
8. [Template do dashboard](#8-template-do-dashboard)

---

## 1. View: OficioProcessarPendentesView

**Arquivo:** `projudi/oficio_views.py` — linhas 260-326

```python
class OficioProcessarPendentesView(LoginRequiredMixin, View):
```

### Explicação

- **`class`** — Define uma classe Python. Uma classe é como um "molde" para criar objetos.
- **`OficioProcessarPendentesView`** — Nome da classe. Segue o padrão Django: `NomeDoRecurso` + `View`.
- **`LoginRequiredMixin`** — Um "mix-in". Garante que o usuário PRECISA estar logado para acessar. Se não estiver, redireciona pro login automaticamente.
- **`View`** — Classe base do Django para views baseadas em classe (CBV).

```python
    """
    POST /projudi/oficios/processar-pendentes/
    Para cada ofício pendente/falhou_email: tenta enviar e-mail.
    Se enviar com sucesso → juntada normal.
    Se falhar → tenta juntada de impossibilidade no Projudi.
    Se também falhar → registra observação local com o motivo.
    """
```

### Explicação

**Docstring** (String de documentação). Explica o que a view faz. Não é executada, mas serve como documentação. Três aspas `"""` permitem texto multilinha.

```python
    def post(self, request):
```

### Explicação

- **`def`** — Define uma função/método.
- **`post`** — Nome do método. No Django, `post` = resposta a requisições HTTP POST (quando um formulário é submetido).
- **`self`** — Referência ao próprio objeto (a instância da classe).
- **`request`** — Objeto que contém TODOS os dados da requisição HTTP (quem fez, que dados enviou, etc.).

```python
        pendentes = OficioRecord.objects.filter(
            user=request.user,
            status__in=['pendente', 'falhou_email']
        )
```

### Explicação

- **`OficioRecord`** — Modelo Django (tabela no banco de dados que guarda ofícios).
- **`.objects`** — Gerenciador de consultas ao banco.
- **`.filter(...)`** — Filtra registros. `__in` significa "em" (qualquer um da lista).
- **`user=request.user`** — Só ofícios do usuário logado.
- **`status__in=['pendente', 'falhou_email']`** — Só ofícios com status "pendente" OU "falhou_email".

**Tradução:** "Busca no banco todos os ofícios que pertencem ao usuário logado E que estão pendentes ou falharam no email."

```python
        if not pendentes:
            messages.info(request, "Nenhum ofício pendente para processar.")
            return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))
```

### Explicação

- **`if not pendentes:`** — Se a lista está vazia (nenhum ofício encontrado).
- **`messages.info(...)`** — Cria uma mensagem informativa pro usuário.
- **`HttpResponseRedirect(...)`** — Redireciona o navegador pra outra página.
- **`reverse('projudi:oficio_dashboard')`** — Gera a URL a partir do nome da rota (não precisa digitar a URL na mão).

```python
        service = OficioService(request.user)
        enviados = 0
        impossibilidade_juntada = 0
        impossibilidade_local = 0
        erros = 0
```

### Explicação

- **`service = OficioService(request.user)`** — Cria uma instância do serviço que orquestra todo o fluxo de ofícios (envio, juntada, etc.).
- **`enviados = 0`** — Contador de ofícios que conseguiram ser enviados por email.
- **`impossibilidade_juntada = 0`** — Contador de ofícios cuja impossibilidade foi para o Projudi.
- **`impossibilidade_local = 0`** — Contador de ofícios cuja impossibilidade ficou só no banco local.
- **`erros = 0`** — Contador de ofícios que deram erro de exceção.

```python
        for record in pendentes:
            try:
                resultado = service.processar_oficio(record)
```

### Explicação

- **`for record in pendentes:`** — Para CADA ofício na lista de pendentes, faça:
- **`try:`** — Tente executar. Se der erro, capture com `except`.
- **`service.processar_oficio(record)`** — Chama o método que processa UM ofício (envia email, junta, etc.).

```python
                if resultado.get('enviado'):
                    enviados += 1
                elif resultado.get('juntado'):
                    impossibilidade_juntada += 1
                else:
                    impossibilidade_local += 1
```

### Explicação

- **`resultado.get('enviado')`** — Pega o valor da chave `'enviado'` do dicionário. Se for True, email foi enviado.
- **`enviados += 1`** — Incrementa o contador (é o mesmo que `enviados = enviados + 1`).
- **`elif`** — "Else if" — se o primeiro if for falso, testa esta condição.
- **`resultado.get('juntado')`** — Se for True, foi juntado no Projudi (não enviou email, mas a impossibilidade foi pro Projudi).
- **`else:`** — Se nenhum dos dois anteriores for verdadeiro.
- **`impossibilidade_local += 1`** — Não enviou e não juntou → registrado localmente.

```python
            except Exception as e:
                erros += 1
                try:
                    service.criar_log(record, 'erro', f"Erro no processamento: {str(e)[:200]}")
                except Exception:
                    pass
```

### Explicação

- **`except Exception as e:`** — Captura QUALQUER erro que acontecer dentro do `try`.
- **`erros += 1`** — Conta como erro.
- **`service.criar_log(...)`** — Registra o erro no log do ofício.
- **`f"Erro no processamento: {str(e)[:200]}"`** — F-string: formata a string com o erro (limitado a 200 caracteres).
- **`try: ... except: pass`** — Se criar o log também der erro, ignora (pass = "não faz nada").

```python
        partes = []
        if enviados:
            partes.append(f"✅ {enviados} ofício(s) enviado(s) e juntado(s) com sucesso")
        if impossibilidade_juntada:
            partes.append(f"📋 {impossibilidade_juntada} ofício(s) juntado(s) no Projudi com declaração de impossibilidade")
        if impossibilidade_local:
            partes.append(
                f"📝 {impossibilidade_local} ofício(s) com impossibilidade registrada localmente "
                f"(não foi possível juntar no Projudi — verifique a sessão e os dados do ofício)"
            )
        if erros:
            partes.append(f"❌ {erros} ofício(s) com erro no processamento. Verifique os logs.")
```

### Explicação

Cria uma lista de mensagens para mostrar ao usuário. Cada `if` adiciona uma mensagem apenas se o contador correspondente for > 0.

```python
        for parte in partes:
            if '✅' in parte:
                messages.success(request, parte)
            elif '❌' in parte:
                messages.error(request, parte)
            else:
                messages.warning(request, parte)
```

### Explicação

Para cada mensagem na lista:
- Se tem ✅ → nível `success` (verde)
- Se tem ❌ → nível `error` (vermelho)
- Senão → nível `warning` (amarelo/laranja)

```python
        return HttpResponseRedirect(reverse('projudi:oficio_dashboard'))
```

Redireciona de volta pro dashboard.

---

## 2. Service: processar_oficio()

**Arquivo:** `projudi/oficio_service.py` — linhas 594-645

```python
    def processar_oficio(self, record: OficioRecord) -> Dict:
```

- **`record: OficioRecord`** — Type hint: diz que o parâmetro `record` é do tipo `OficioRecord`.
- **`-> Dict`** — Type hint: diz que o método retorna um dicionário.

```python
        resultado = {
            'enviado': False,
            'juntado': False,
            'erro': None,
        }
```

Dicionário que guarda o resultado da operação. Começa tudo falso/nulo.

```python
        if record.juntado:
            self._log(record, 'info',
                "Oficio ja consta como juntado. Nenhuma acao necessaria.",
                {'acao': 'skip'}
            )
            resultado['juntado'] = True
            return resultado
```

Se o ofício já está como "juntado", não faz nada e retorna.

```python
        ok_envio, info = self.enviar_email(record)
```

Chama o método que envia o email. Retorna:
- `ok_envio`: True se enviou, False se falhou
- `info`: Se enviou → ID da mensagem; Se falhou → mensagem de erro

```python
        if ok_envio:
            resultado['enviado'] = True
            resultado['juntado'] = self.juntar_cumprimento(record)
```

Se enviou → marca como enviado e tenta juntar no Projudi.

```python
        else:
            resultado['erro'] = info
            motivo_humanizado = self.humanizar_erro(info)
```

Se **NÃO** enviou → guarda o erro e HUMANIZA (traduz pra linguagem de usuário comum).

```python
            try:
                ok_impossibilidade = self.juntar_resposta_impossibilidade(
                    record, motivo=motivo_humanizado
                )
```

Tenta juntar a impossibilidade no Projudi com o motivo humanizado.

```python
                if ok_impossibilidade:
                    resultado['juntado'] = True
                else:
                    observacao = (
                        f"Não foi possível enviar o Ofício {record.numero_oficio} "
                        f"em {timezone.now().strftime('%d/%m/%Y %H:%M')}.\n"
                        f"Motivo: {motivo_humanizado}\n"
                        f"A juntada no Projudi não pôde ser concluída "
                        f"(sessão indisponível ou dados do ofício incompletos). "
                        f"Providencie o encaminhamento manual pelo Cartório."
                    )
                    record.observacao_retorno = observacao
                    record.save(update_fields=['observacao_retorno'])
```

Se a juntada no Projudi também falhar:
- Cria um texto de observação com o motivo
- Salva no campo `observacao_retorno` do ofício (visível no dashboard)
- `update_fields` = só atualiza esse campo (mais eficiente)

---

## 3. Texto de Impossibilidade

**Arquivo:** `projudi/oficio_service.py` — linhas 580-589

```python
    def _gerar_texto_impossibilidade(self, record: OficioRecord, motivo: str = "") -> str:
        motivo_final = motivo or "e-mail de destinatario ausente ou invalido"
        texto = (
            f"Impossibilidade de cumprimento do Oficio n {record.numero_oficio}, "
            f"processo {record.numero_processo_cnj or record.processo}. Motivo: {motivo_final}. "
            f"Foi tentado o envio automatico em {datetime.now().strftime('%d/%m/%Y %H:%M')} "
            f"sem exito. Aguarda providencias do Cartorio para novo encaminhamento."
        )
        return texto
```

### Linha a linha:

- **`motivo: str = ""`** — Parâmetro opcional. Se não passar, string vazia.
- **`motivo_final = motivo or "e-mail..."`** — Se motivo for vazio, usa o fallback.
- **`or`** funciona como: se o primeiro for "falso" (vazio, None, 0), usa o segundo.
- **`f"..."`** — F-string. Tudo dentro de `{}` é código Python executado e convertido pra string.
- **`{record.numero_oficio}`** — Pega o número do ofício do objeto.
- **`{record.numero_processo_cnj or record.processo}`** — Usa CNJ se tiver, senão usa o número interno.
- **`{datetime.now().strftime('%d/%m/%Y %H:%M')}`** — Data/hora atual formatada: dia/mês/ano hora:minuto.
- **`\n`** — Não aparece aqui, mas se tivesse, seria quebra de linha.

---

## 4. Humanização de Erros

**Arquivo:** `projudi/oficio_service.py` — linhas 713-742

```python
    def humanizar_erro(self, erro: str) -> str:
        """Traduz erros tecnicos para linguagem nao-tecnica."""
        erro = str(erro).lower()
        
        if 'nenhum e-mail' in erro or 'email de destino' in erro or 'sem email' in erro:
            return "o oficio não possui e-mail de destinatário."
        
        if 'jsessionid' in erro or 'sessao' in erro or 'expirada' in erro:
            return "A sessao do Projudi expirou..."
        # ...
```

### Lógica:

1. **`erro = str(erro).lower()`** — Converte pra string minúscula (pra comparação não ser sensível a maiúscula/minúscula).
2. **`if 'palavra' in erro`** — Verifica se a string `erro` CONTÉM a palavra. É tipo um "CTRL+F": se achar, é True.
3. **`or`** — OU lógico. Qualquer um dos três que aparecer, cai no if.
4. **Ordem importa!** — O if do "nenhum e-mail" vem ANTES do if genérico de email. Se viesse depois, cairia no "smtp/email/gmail".

### Por que essa ordem?

```python
# ORDEM ERRADA:
if 'smtp' in erro or 'email' in erro or 'gmail' in erro:
    return "Verifique a senha de app..."  # ← pegaria o erro de "sem email" também!

# ORDEM CERTA:
if 'nenhum e-mail' in erro or 'email de destino' in erro:  # ← mais específico PRIMEIRO
    return "o oficio não possui email..."
if 'smtp' in erro or 'email' in erro:  # ← depois o genérico
    return "Verifique a senha de app..."
```

**Regra:** Sempre colocar o caso mais específico ANTES do mais genérico.

---

## 5. Captura de Sessão (4 Camadas)

**Arquivo:** `projudi/services.py` — linhas 69-175

```python
    def _get_session_from_cookies(self):
        """
        Cria um requests.Session a partir dos cookies.
        Prioridade:
        1. /mnt/d/Projudi/cookies.json
        2. powershell.exe → capture_cookies_windows.py
        3. browser_cookie3.firefox()
        4. ProjudiSession (banco)
        """
```

### O underscore `_` no nome do método

Em Python, `_` no início de um nome significa "privado" — não deve ser chamado de fora da classe. É uma convenção, não uma regra forçada.

### Função interna: `_criar_session`

```python
        def _criar_session(cookies_dict):
            session = requests.Session()
            for name, value in cookies_dict.items():
                session.cookies.set(name, value)
            session.headers.update({
                "User-Agent": "Mozilla/5.0 ... Firefox/128.0",
                ...
            })
            return session, cookies_dict
```

- **Função dentro de função** — Só existe dentro de `_get_session_from_cookies`. Evita repetir código.
- **`requests.Session()`** — Cria uma sessão HTTP que mantém cookies entre requisições.
- **`for name, value in cookies_dict.items():`** — Itera por cada par chave→valor do dicionário.
- **`session.cookies.set(name, value)`** — Adiciona cada cookie na sessão.
- **`session.headers.update({...})`** — Define headers HTTP comuns (User-Agent, etc.) pra parecer um navegador real.

### Camada 1: Arquivo JSON

```python
        for caminho in caminhos_json:
            if caminho.exists():
                try:
                    with open(caminho, 'r', encoding='utf-8') as f:
                        cookies_dict = json.load(f)
                    if 'JSESSIONID' in cookies_dict:
                        # Atualiza sessão no banco
                        ProjudiSession.objects.update_or_create(...)
                        # Aquecer sessão
                        session, _ = _criar_session(cookies_dict)
                        session.get("...AnalisarMovimentacao", timeout=10)
                        return session, cookies_dict
                except Exception:
                    pass
```

- **`caminho.exists()`** — Verifica se o arquivo existe no disco.
- **`with open(...) as f:`** — Abre o arquivo e fecha automaticamente ao sair do bloco.
- **`json.load(f)`** — Lê o JSON e converte pra dicionário Python.
- **`if 'JSESSIONID' in cookies_dict:`** — Só usa se tiver o cookie essencial.
- **`update_or_create(...)`** — Atualiza ou cria um registro no banco.
- **Aquecer:** Faz um GET pro Projudi pra "acordar" a sessão antes de usar.
- **`except Exception: pass`** — Se algo der errado (arquivo corrompido, JSON inválido), tenta o próximo caminho.

### Camada 2: powershell.exe

```python
        try:
            script_path = 'D:\\Projudi\\capture_cookies_windows.py'
            result = subprocess.run(
                ['powershell.exe', '-Command',
                 f'python "{script_path}" --quiet'],
                capture_output=True, text=True, timeout=30,
            )
            # Re-tenta ler após captura
            for caminho in caminhos_json:
                if caminho.exists():
                    try:
                        with open(caminho, 'r') as f:
                            cookies_dict = json.load(f)
                        if 'JSESSIONID' in cookies_dict:
                            ...
                            return session, cookies_dict
                    except Exception:
                        pass
        except Exception:
            pass
```

- **`subprocess.run(...)`** — Executa um comando no sistema operacional (fora do Python).
- **`['powershell.exe', '-Command', ...]`** — Chama o PowerShell do Windows.
- **`timeout=30`** — Se o comando demorar mais de 30 segundos, cancela.
- **`capture_output=True`** — Captura a saída do comando.
- **Depois de rodar o script, TENTA LER DE NOVO** o arquivo JSON (que pode ter sido atualizado).

### Camada 3: browser_cookie3

```python
        try:
            import browser_cookie3
            cj = browser_cookie3.firefox(domain_name='projudi.tjba.jus.br')
            cookies_ff = {c.name: c.value for c in cj}
            if cookies_ff and 'JSESSIONID' in cookies_ff:
                # Salva no arquivo e no banco
                ...
                return session, cookies_ff
        except Exception:
            pass
```

- **`browser_cookie3.firefox(domain_name=...)`** — Tenta ler cookies do Firefox para o domínio especificado.
- **{c.name: c.value for c in cj}** — "Dict comprehension": cria um dicionário iterando sobre os cookies.
- No WSL não funciona para session cookies (JSESSIONID). No Windows sim.

### Camada 4: ProjudiSession (banco)

```python
        sessao = ProjudiSession.objects.filter(user=self.user, status='active').first()
        if sessao and sessao.cookies:
            cookies_dict = sessao.cookies if isinstance(sessao.cookies, dict) else {}
            if 'JSESSIONID' in cookies_dict:
                session, _ = _criar_session(cookies_dict)
                return session, cookies_dict

        print("[WARN] _get_session_from_cookies: JSESSIONID não encontrado em nenhuma fonte")
        return None
```

Último recurso: usa o que está salvo no banco (provavelmente expirado). Se nada funcionar, retorna `None`.

---

## 6. Script de Captura de Cookies

**Arquivo:** `scripts/capture_cookies_windows.py`

```python
def capture_cookies(quiet=False):
    """Captura cookies do Firefox via browser_cookie3."""
    browsers = ['firefox', 'chrome', 'edge']
    
    for browser_name in browsers:
        try:
            cj = getattr(browser_cookie3, browser_name)(domain_name=DOMAIN)
            cookies = {c.name: c.value for c in cj}
            
            if cookies:
                return cookies
        except Exception:
            pass
    
    return {}
```

- **`getattr(browser_cookie3, browser_name)`** — Pega o método do módulo pelo nome. É o mesmo que fazer `browser_cookie3.firefox` mas sem precisar de if/elif.
- **`cj`** — CookieJar (objeto que contém cookies).
- **`{c.name: c.value for c in cj}`** — Dict comprehension: para cada cookie c em cj, cria uma entrada nome→valor.

### Modo --quiet

```python
def main():
    quiet = '--quiet' in sys.argv
    
    cookies = capture_cookies(quiet=quiet)
    
    if not cookies:
        if quiet:
            return 1  # sai silenciosamente (código 1 = erro)
        print("\n[ERRO] Nenhum cookie encontrado!")
        return 1
    
    save_cookies(cookies)
    
    if not quiet:
        # Só keep-alive no modo interativo
        try:
            while True:
                time.sleep(60)
                ...
```

### Função save_cookies

```python
def save_cookies(cookies):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)
```

- **`mkdir(parents=True, exist_ok=True)`** — Cria diretório se não existir (como `mkdir -p` no Linux).
- **`json.dump(cookies, f, indent=2)`** — Salva o dicionário como JSON formatado (com indentação de 2 espaços).

---

## 7. URLs e Rotas

**Arquivo:** `projudi/urls.py`

```python
path('oficios/processar-pendentes/',
     oficio_views.OficioProcessarPendentesView.as_view(),
     name='oficio_processar_pendentes'),
```

- **`path('oficios/processar-pendentes/', ...)`** — Quando alguém acessar `/projudi/oficios/processar-pendentes/`, chama esta view.
- **`.as_view()`** — Método do Django que transforma a classe View em uma função que o Django pode chamar.
- **`name='...'`** — Nome único pra rota. Usado no template com `{% url 'projudi:oficio_processar_pendentes' %}` e no Python com `reverse('projudi:oficio_processar_pendentes')`.

---

## 8. Template do Dashboard

**Arquivo:** `templates/projudi/oficio_dashboard.html` — linhas 111-116

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

- **`<form method="post">`** — Formulário que envia via POST (não GET).
- **`{% url '...' %}`** — Tag Django: gera a URL a partir do nome da rota.
- **`{% csrf_token %}`** — Tag Django: insere um token de segurança contra CSRF (Cross-Site Request Forgery). Todo formulário POST no Django precisa disso.
- **`style="..."`** — CSS inline:
  - `linear-gradient(135deg,#7c3aed,#a855f7)` — Gradiente roxo (mesmo estilo do botão ⚡ Expedir).
  - `box-shadow: 0 2px 8px rgba(124,58,237,0.4)` — Sombra roxa pra destacar.

---

## 📋 Glossário de Termos

| Termo | Explicação |
|-------|-----------|
| **View** | Função (ou classe) que recebe uma requisição HTTP e retorna uma resposta |
| **Model** | Classe Django que representa uma tabela no banco de dados |
| **Mix-in** | Classe pequena que adiciona funcionalidade a outra (como `LoginRequiredMixin`) |
| **Type hint** | Dica de tipo (`record: OficioRecord`). Python ignora, mas ajuda programadores |
| **F-string** | String formatada: `f"Olá {nome}"` → substitui `{nome}` pelo valor da variável |
| **Dict comprehension** | `{chave: valor for item in lista}` — cria dicionário de forma concisa |
| **CSRF Token** | Token de segurança embutido no formulário pra evitar ataques |
| **Subprocess** | Executar um comando no sistema operacional a partir do Python |
| **DPAPI** | Criptografia nativa do Windows para dados de aplicativos (incluindo cookies) |
| **JSESSIONID** | Cookie de sessão do servidor Java do Projudi |
