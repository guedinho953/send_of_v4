# CONHECIMENTOS PROFISSIONAIS - Cartorio Digital

## Conceitos que voce agora domina

### 1. HTTP Requests vs Browser Automation

**Requests (o que usamos agora):**
- Comunicacao direta servidor-cliente
- Usa cookies para manter sessao
- Rapido e confiavel
- Ideal para formularios simples e APIs

**Selenium (o que tinhamos antes):**
- Controla navegador real
- Executa JavaScript
- Renderiza pagina completa
- Lento e sujeito a race conditions

**Regra de ouro:**
> Se a pagina funciona com requests, NAO use Selenium.
> So use Selenium se a pagina depende de JavaScript para funcionar.

### 2. Sessao e Cookies

**Como funciona:**
1. Voce faz login -> servidor da um cookie (JSESSIONID)
2. Voce envia o cookie em TODAS as requisicoes seguintes
3. Servidor reconhece voce pelo cookie
4. Cookie expira (30 min no Projudi)

**Por que cookies do Firefox funcionam no requests:**
- Cookie e so um texto que o navegador guarda
- Requests pode enviar o mesmo texto
- Servidor nao sabe se veio do Firefox ou do requests

### 3. Scraping de Formularios

**Padrao universal:**
```
1. GET pagina -> recebe HTML com formulario
2. Parse HTML -> extrai inputs hidden (dados de estado)
3. Preenche campos visiveis
4. POST para action do form
5. Verifica resposta
```

**Por que extrair inputs hidden:**
- Eles contem dados que o servidor precisa (codDocVinculado, codGrupo)
- Sem eles, o POST falha
- Cada pagina tem valores diferentes

### 4. Django Templates e Filtros

**Filtros customizados:**
```python
# Criar em templatetags/
@register.filter
def formatar_processo(numero):
    # Logica de formatacao
    return numero_formatado

# Usar no template
{{ processo|formatar_processo }}
```

**Por que usar:**
- Separa logica de apresentacao
- Reutilizavel em varios templates
- Testavel isoladamente

### 5. Padroes de Projeto

**Lazy Initialization:**
```python
@property
def juntada(self):
    if self._juntada is None:
        self._juntada = criar_juntada()
    return self._juntada
```
- Cria objeto so quando precisa
- Economiza recursos
- Facilita testes

**Separation of Concerns:**
- Model: dados (OficioRecord)
- View: interface (templates)
- Service: logica de negocio (OficioService)
- Repository: acesso a dados (models.py)

### 6. Ambiente WSL

**WSL = Windows Subsystem for Linux**
- Linux rodando dentro do Windows
- Compartilha arquivos via /mnt/c/, /mnt/d/
- Servidor no WSL acessivel pelo Windows em localhost

**Importante:**
- Servidor morre se fechar terminal
- Usar --noreload para evitar duas instancias
- Firefox no WSL precisa de geckodriver

### 7. Git e Versionamento

**Commits semanticos:**
```
feat: juntada via requests sem selenium
fix: corrige numero do processo para CNJ
docs: adiciona documentacao da juntada
```

**Nunca commitar:**
- Senhas (.env)
- Arquivos de cache (__pycache__)
- Banco de dados de producao

### 8. Seguranca Web

**Headers importantes:**
```
User-Agent: identifica o navegador
Cookie: mantem sessao
Referer: de onde veio a requisicao
Content-Type: tipo do dado enviado
```

**HTTPS:**
- Sempre usar em producao
- Cookie 'secure=True' so funciona em HTTPS
- Projudi usa HTTPS (obrigatorio)

### 9. Debugging HTTP

**Ferramentas:**
```bash
# Ver requisicoes
httpie GET http://localhost:8000/api/

# Inspecionar cookies
curl -v http://localhost:8000/login/

# Proxy para debug
# Charles Proxy, Fiddler, Burp Suite
```

**Salvar HTML:**
```python
with open('debug.html', 'w') as f:
    f.write(response.text)
# Abrir no navegador para inspecionar
```

### 10. Performance

**O que deixa lento:**
- Abrir navegador (Selenium) = 5-10s
- Renderizar pagina = 2-3s
- Esperar elementos = 1-5s
- **Total: 10-20s por juntada**

**O que e rapido:**
- Requests GET = 0.5s
- Parse HTML = 0.1s
- POST = 0.5s
- **Total: 1-2s por juntada**

**Speedup: 10x mais rapido!**

---

## Dicionario Tecnico

| Termo | Significado | Exemplo |
|-------|-------------|---------|
| Cookie | Identificador de sessao | JSESSIONID=abc123 |
| Session | Conexao persistente | requests.Session() |
| Payload | Dados enviados no POST | formulario preenchido |
| Parser | Extrai dados de HTML | BeautifulSoup |
| Headless | Sem interface grafica | firefox --headless |
| User-Agent | Identifica navegador | Mozilla/5.0... |
| CSRF | Protecao contra ataque | token nos forms |
| QuerySet | Busca no banco | OficioRecord.objects.filter(...) |
| Migration | Alteracao no banco | makemigrations |
| Template | Arquivo HTML | oficio_dashboard.html |
| Static | Arquivos CSS/JS | style.css |
| Media | Uploads de usuario | documentos.pdf |

---

## Proximos temas para estudar

1. **REST APIs** - Como criar APIs com Django REST Framework
2. **Celery** - Tarefas assincronas (enviar email em background)
3. **Docker** - Containerizar a aplicacao
4. **Tests** - pytest, coverage, TDD
5. **CI/CD** - GitHub Actions para deploy automatico
6. **React/Vue** - Frontend moderno consumindo API

---

*Gerado em 10/07/2026*
