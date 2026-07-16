"""
Guia de Integração - Fluxo Contínuo

Este documento mostra como todos os módulos se conectam.
"""

# =============================================================================
# ARQUITETURA DO FLUXO CONTÍNUO
# =============================================================================

"""
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PIPELINE CONTÍNUO SCCJ                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 1. INICIALIZAÇÃO                                                     │   │
│  │    ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐     │   │
│  │    │ ProjudiBot   │───>│ProjudiClient │───>│PipelineOrchestr. │     │   │
│  │    │ (sessão)     │    │(navegação)   │    │  (orquestrador)  │     │   │
│  │    └──────────────┘    └──────────────┘    └──────────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 2. LISTAR MOVIMENTAÇÕES PENDENTES                                    │   │
│  │    ProjudiClient.extrair_links_movimentacoes()                       │   │
│  │    → Retorna: [{processo, tipo, link_documento, movimentar, ...}]    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 3. PARA CADA MOVIMENTAÇÃO                                            │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ 3a. EXTRAIR TEXTO DO DOCUMENTO                             │   │   │
│  │    │     session.get(link_documento)                            │   │   │
│  │    │     DocumentAnalyzer.extrair_texto_documento(html)         │   │   │
│  │    │     → texto limpo e pronto para análise                    │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ 3b. ANALISAR COMANDOS JUDICIAIS                            │   │   │
│  │    │     DocumentAnalyzer.analisar_movimentacao(texto, mov)     │   │   │
│  │    │     CommandAnalyzer.processar_texto(texto, item)           │   │   │
│  │    │     → [{comando, meio, quando, condicao, prazo}]           │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ 3c. BUSCAR PADRÕES SIMILARES (RAG - opcional)              │   │   │
│  │    │     RAGPipeline.find_successful_compliances(comando)       │   │   │
│  │    │     → [{tipo_acao, descricao, passos, status}]             │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ 3d. QWEN SUGERE PLANO DE CUMPRIMENTO                       │   │   │
│  │    │     QwenDocumentGenerator.sugerir_plano_cumprimento()      │   │   │
│  │    │     → {plano_sugerido: {tipo_acao, passos, ...}}           │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ 3e. APROVAÇÃO DO USUÁRIO (se auto_executar=False)          │   │   │
│  │    │     Mostra comandos + plano sugerido                       │   │   │
│  │    │     Usuário decide: [s]im / [N]ão / [q]uit               │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ 3f. EXECUTAR CUMPRIMENTO                                   │   │   │
│  │    │     ┌─────────────────────────────────────────────────┐   │   │   │
│  │    │     │ Opção A: Ofício via Email + Juntada             │   │   │   │
│  │    │     │   OficioExtractor.extrair_de_html()             │   │   │   │
│  │    │     │   EmailSender.enviar_oficio()                   │   │   │   │
│  │    │     │   ProjudiJuntada.realizar_juntada()             │   │   │   │
│  │    │     │   ProtocoloCSV.registrar_envio()                │   │   │   │
│  │    │     └─────────────────────────────────────────────────┘   │   │   │
│  │    │     ┌─────────────────────────────────────────────────┐   │   │   │
│  │    │     │ Opção B: Juntada Direta                         │   │   │   │
│  │    │     │   ProjudiJuntada.realizar_juntada()             │   │   │   │
│  │    │     └─────────────────────────────────────────────────┘   │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ 3g. QWEN VERIFICA CONSISTÊNCIA                             │   │   │
│  │    │     QwenDocumentGenerator.verificar_consistencia()         │   │   │
│  │    │     → {consistente: bool, justificativa, observacoes}      │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │    ┌────────────────────────────────────────────────────────────┐   │   │
│  │    │ 3h. INDEXAR PARA RAG FUTURO                                │   │   │
│  │    │     RAGPipeline.index_compliance()                         │   │   │
│  │    │     → Armazena no pgvector para buscas futuras             │   │   │
│  │    └────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 4. RESUMO FINAL                                                      │   │
│  │    PipelineOrchestrator._log_resumo()                                │   │
│  │    → Total, concluídos, falharam, dispensados                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""

# =============================================================================
# MAPEAMENTO DE MÓDULOS
# =============================================================================

MODULE_MAP = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MAPEAMENTO DE MÓDULOS                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  MÓDULOS EXISTENTES (send_of_v2):                                           │
│  ─────────────────────────────────                                          │
│  projudi_bot.py          → ProjudiBot                                       │
│                            • Captura cookies do Firefox                     │
│                            • Mantém sessão ativa (keep_alive)               │
│                                                                             │
│  projudi_client.py       → ProjudiClient                                    │
│                            • Navega páginas Projudi                         │
│                            • extrair_links_movimentacoes()                  │
│                            • extrair_links_oficios()                        │
│                                                                             │
│  projudiProcessNavigator → ProcessoParser                                   │
│                            • extrair_partes()                               │
│                            • extrair_movimentacoes()                        │
│                                                                             │
│  projudiDocReader.py     → DocumentAnalyzer                                 │
│                            • extrair_texto_documento()                      │
│                            • analisar_movimentacao()                        │
│                            • extrair_comandos()                             │
│                                                                             │
│  projudi_command_analyzer → CommandAnalyzer                                 │
│                            • processar_texto()                              │
│                            • salvar_no_banco() (SQLite)                     │
│                                                                             │
│  MÓDULOS NOVOS (refatorados):                                               │
│  ─────────────────────────                                                  │
│  exemplo_refatoracao_oo.py:                                                 │
│                            → EmailSender                                    │
│                            → ProjudiJuntada                                 │
│                            → OficioProcessor                                │
│                            → OficioExtractor                                │
│                            → ProtocoloCSV                                   │
│                                                                             │
│  qwen_integration.py     → QwenDocumentGenerator                            │
│                            • gerar_oficio()                                 │
│                            • verificar_consistencia()                       │
│                            • sugerir_plano_cumprimento()                    │
│                                                                             │
│  pipeline_orchestrator.py → PipelineOrchestrator                            │
│                            • executar_pipeline_completo()                   │
│                            • Integra TODOS os módulos acima                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""

# =============================================================================
# EXEMPLO DE USO RÁPIDO
# =============================================================================

USAGE_EXAMPLE = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXEMPLO DE USO                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  # 1. Importar orquestrador                                                 │
│  from pipeline_orchestrator import PipelineOrchestrator, PipelineConfig     │
│  from qwen_integration import LlamaBackend                                  │
│                                                                             │
│  # 2. Configurar                                                            │
│  config = PipelineConfig(                                                   │
│      email_remetente='pafonso.2vsj@gmail.com',                              │
│      email_senha_app='sua_senha_app',                                       │
│      qwen_backend=LlamaBackend.SERVER,                                      │
│      qwen_server_url="http://localhost:8080",                               │
│      auto_executar=False,  # Pede aprovação                                 │
│      usar_qwen_verificacao=True,                                            │
│  )                                                                          │
│                                                                             │
│  # 3. Executar                                                              │
│  pipeline = PipelineOrchestrator(config)                                    │
│  results = pipeline.executar_pipeline_completo()                            │
│                                                                             │
│  # 4. Ver resultados                                                        │
│  for r in results:                                                          │
│      print(f"{r.processo}: {r.status.value}")                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""

# =============================================================================
# DEPENDÊNCIAS
# =============================================================================

DEPENDENCIES = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DEPENDÊNCIAS                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  pip install:                                                               │
│  ──────────                                                                 │
│  requests              # HTTP client                                        │
│  beautifulsoup4        # HTML parsing                                       │
│  selenium              # Automação browser                                  │
│  webdriver-manager     # Gecko driver                                       │
│  browser-cookie3       # Captura cookies Firefox                            │
│  sentence-transformers # Embeddings para RAG                                │
│  llama-cpp-python      # (opcional) Binding Python para llama.cpp           │
│  psycopg2-binary       # PostgreSQL                                         │
│  django                # Framework                                          │
│                                                                             │
│  Externo:                                                                   │
│  ────────                                                                   │
│  llama.cpp server      # Rodar: ./llama-server -m qwen2.5.gguf --port 8080 │
│  PostgreSQL + pgvector # Para RAG (opcional na fase inicial)                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""

# =============================================================================
# PRÓXIMOS PASSOS
# =============================================================================

NEXT_STEPS = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRÓXIMOS PASSOS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  FASE 1: Integração Básica (1-2 dias)                                       │
│  ──────────────────────────────────                                         │
│  [ ] Testar PipelineOrchestrator com movimentações reais                    │
│  [ ] Validar fluxo: bot → client → doc_analyzer → processor                 │
│  [ ] Ajustar delays e tratamento de erros                                   │
│                                                                             │
│  FASE 2: Qwen Integration (1 dia)                                           │
│  ──────────────────────────────                                             │
│  [ ] Iniciar llama.cpp server                                               │
│  [ ] Testar sugerir_plano_cumprimento()                                     │
│  [ ] Testar verificar_consistencia()                                        │
│  [ ] Ajustar prompts para melhor qualidade                                  │
│                                                                             │
│  FASE 3: RAG com pgvector (2-3 dias)                                        │
│  ──────────────────────────────────                                         │
│  [ ] Configurar PostgreSQL + pgvector                                       │
│  [ ] Implementar VectorEmbedding model                                      │
│  [ ] Migrar dados do SQLite para PostgreSQL                                 │
│  [ ] Indexar cumprimentos históricos                                        │
│  [ ] Testar busca por similaridade                                          │
│                                                                             │
│  FASE 4: Django Integration (3-5 dias)                                      │
│  ────────────────────────────────────                                       │
│  [ ] Criar apps Django                                                      │
│  [ ] Migrar models                                                          │
│  [ ] Criar views e templates                                                │
│  [ ] Integrar Celery para tasks async                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""


def print_guide():
    """Imprime o guia completo"""
    print(MODULE_MAP)
    print(USAGE_EXAMPLE)
    print(DEPENDENCIES)
    print(NEXT_STEPS)


if __name__ == "__main__":
    print_guide()
