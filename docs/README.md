# 📚 Documentação — send_of_v4

> Data da documentação: 2026-07-17
> Última atualização: 2026-07-17

---

## Índice

| # | Documento | Conteúdo | Pra quê |
|---|-----------|----------|---------|
| 01 | [BANCO-DE-DADOS](01-BANCO-DE-DADOS.md) | PostgreSQL, containers, backup | Subir o servidor |
| 02 | [SESSAO-PROJUDI](02-SESSAO-PROJUDI.md) | JSESSIONID, captura de cookies | Manter sessão ativa |
| 03 | [PROCESSAR-PENDENTES](03-PROCESSAR-PENDENTES.md) | View, fluxo de impossibilidade | Como funciona o botão |
| 04 | [MODO-ESTUDANTE](04-MODO-ESTUDANTE.md) | Explicação linha por linha | Aprender o código |
| 05 | [CONFIGURAR-RAGS](05-CONFIGURAR-RAGS.md) | sequencia_cumprimento: tipos de passo, códigos (localizador, subtipo, prazo), polo, exemplos | Configurar RAGExamples |

---

## Modo Desenvolvedor (referência rápida)

```
docs/01-BANCO-DE-DADOS.md    → Comandos para subir o banco
docs/02-SESSAO-PROJUDI.md    → Como capturar cookies
docs/03-PROCESSAR-PENDENTES.md → Fluxo do botão
```

## Modo Estudante (aprender)

```
docs/04-MODO-ESTUDANTE.md     → Explicação de CADA linha
```

---

## Skills do Hermes

 Skills relacionadas:
- `projudi/expedir-oficio-ciap` — Expedição de ofício CIAP
- `projudi/projudi-automacao-playwright` — Automação geral Projudi (inclui sessão)
- `devops/postgresql-docker-volume` — Gerenciamento do PostgreSQL

---

## Arquivos importantes

| Arquivo | Descrição |
|---------|-----------|
| `~/PythonProjects/send_of_v4/` | Raiz do projeto |
| `projudi/oficio_views.py` | Views de ofícios (inclui `OficioProcessarPendentesView`) |
| `projudi/oficio_service.py` | Service de ofícios (`processar_oficio`, `humanizar_erro`) |
| `projudi/services.py` | Service geral (`_get_session_from_cookies`) |
| `projudi/urls.py` | Rotas do app projudi |
| `templates/projudi/oficio_dashboard.html` | Dashboard de ofícios |
| `scripts/capture_cookies_windows.py` | Script de captura de cookies (Windows) |
| `/mnt/d/Projudi/cookies.json` | Arquivo de cookies |
| `/mnt/d/Projudi/capture_cookies_windows.py` | Cópia do script para Windows |
| `scripts/backup_db.sh` | Backup do banco |
| `docs/` | Esta documentação |
