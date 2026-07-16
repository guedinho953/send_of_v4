"""
Pipeline Contínuo - Orquestrador

Integra todos os módulos em um fluxo unificado:

ProjudiBot → ProjudiClient → DocumentAnalyzer → CommandAnalyzer 
→ RAG Pipeline → Qwen → EmailSender + ProjudiJuntada → ProtocoloCSV

Fluxo:
1. Inicia sessão no Projudi
2. Lista movimentações pendentes
3. Para cada movimentação:
   a. Extrai e analisa comandos judiciais
   b. Busca padrões similares (RAG)
   c. Qwen sugere plano de cumprimento
   d. Executa cumprimento (email + juntada)
   e. Registra e indexa para RAG futuro
"""

import time
import random
from datetime import datetime
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urljoin
import logging

from bs4 import BeautifulSoup

# Módulos existentes
from projudi_bot import ProjudiBot
from projudi_client import ProjudiClient
from projudiDocReader import DocumentAnalyzer
from projudi_command_analyzer_new import CommandAnalyzer
from projudiProcessNavigator import ProcessoParser

# Módulos novos (refatorados)
from exemplo_refatoracao_oo import (
    EmailSender, EmailConfig,
    ProjudiJuntada, ProjudiConfig,
    OficioProcessor, OficioExtractor, ProtocoloCSV,
    OficioData
)

# Integração Qwen (OPCIONAL - só importa se usar_qwen=True)
try:
    from qwen_integration import QwenDocumentGenerator, LlamaConfig, LlamaBackend
    QWEN_AVAILABLE = True
except ImportError:
    QWEN_AVAILABLE = False
    QwenDocumentGenerator = None
    LlamaConfig = None
    LlamaBackend = None


# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('PipelineOrchestrator')


# =============================================================================
# ESTADOS DO PIPELINE
# =============================================================================

class PipelineStatus(Enum):
    """Status de processamento de uma movimentação"""
    PENDENTE = "pendente"
    EM_ANALISE = "em_analise"
    COMANDOS_EXTRAIDOS = "comandos_extraidos"
    PLANO_GERADO = "plano_gerado"
    EM_EXECUCAO = "em_execucao"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    DISPENSADO = "dispensado"


@dataclass
class PipelineResult:
    """Resultado do processamento de uma movimentação"""
    processo: str
    tipo: str
    status: PipelineStatus = PipelineStatus.PENDENTE
    comandos: List[Dict] = field(default_factory=list)
    plano_sugerido: Optional[Dict] = None
    verificacao_consistencia: Optional[Dict] = None
    email_enviado: bool = False
    juntada_realizada: bool = False
    erro: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


# =============================================================================
# CONFIGURAÇÃO DO PIPELINE
# =============================================================================

@dataclass
class PipelineConfig:
    """Configuração completa do pipeline"""
    
    # Email
    email_remetente: str = 'pafonso.2vsj@gmail.com'
    email_senha_app: str = ''
    
    # Projudi
    projudi_link_base: str = 'https://projudi.tjba.jus.br/projudi/'
    projudi_codigo_juntada: str = '581'
    
    # Qwen / llama.cpp (OPCIONAL)
    usar_qwen: bool = False  # Ativa/desativa Qwen completamente
    qwen_backend: str = "server"  # "server" ou "python"
    qwen_server_url: str = "http://localhost:8080"
    qwen_model_path: str = ""
    
    # CSV
    protocolo_csv_path: str = 'protocolo_email_projudi.csv'
    
    # Comportamento
    delay_min: float = 1.0
    delay_max: float = 5.0
    max_paginas: int = 3
    auto_executar: bool = False  # Se True, executa sem aprovação
    usar_qwen_verificacao: bool = False  # Verificar consistência com Qwen
    usar_qwen_plano: bool = False  # Gerar plano com Qwen
    usar_rag: bool = False  # Busca por similares (requer pgvector)
    
    # Callbacks
    on_command_extracted: Optional[Callable] = None
    on_plan_generated: Optional[Callable] = None
    on_before_execute: Optional[Callable] = None


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

class PipelineOrchestrator:
    """
    Orquestra o fluxo completo de cumprimento judicial.
    
    Integra:
    - ProjudiBot (sessão)
    - ProjudiClient (navegação)
    - DocumentAnalyzer (extração de comandos)
    - CommandAnalyzer (análise detalhada)
    - QwenDocumentGenerator (verificação + sugestão)
    - EmailSender + ProjudiJuntada (execução)
    - ProtocoloCSV (registro)
    """
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        
        # Componentes (inicializados lazy)
        self._bot: Optional[ProjudiBot] = None
        self._client: Optional[ProjudiClient] = None
        self._doc_analyzer: Optional[DocumentAnalyzer] = None
        self._cmd_analyzer: Optional[CommandAnalyzer] = None
        self._process_parser: Optional[ProcessoParser] = None
        self._qwen: Optional[QwenDocumentGenerator] = None
        self._email_sender: Optional[EmailSender] = None
        self._juntada: Optional[ProjudiJuntada] = None
        self._processor: Optional[OficioProcessor] = None
        self._protocolo: Optional[ProtocoloCSV] = None
        self._extractor: Optional[OficioExtractor] = None
        
        # RAG (opcional)
        self._rag_pipeline = None
        
        # Estado
        self._results: List[PipelineResult] = []
        self._running = False
    
    # -------------------------------------------------------------------------
    # INICIALIZAÇÃO LAZY
    # -------------------------------------------------------------------------
    
    @property
    def bot(self) -> ProjudiBot:
        if self._bot is None:
            logger.info("Inicializando ProjudiBot...")
            self._bot = ProjudiBot()
            self._bot.executar()
            if not self._bot._keep_alive:
                raise RuntimeError("Não foi possível estabelecer sessão com Projudi")
            logger.info("✅ Sessão Projudi estabelecida")
        return self._bot
    
    @property
    def client(self) -> ProjudiClient:
        if self._client is None:
            logger.info("Inicializando ProjudiClient...")
            self._client = ProjudiClient()
            self._client.iniciar()
            logger.info("✅ ProjudiClient inicializado")
        return self._client
    
    @property
    def doc_analyzer(self) -> DocumentAnalyzer:
        if self._doc_analyzer is None:
            self._doc_analyzer = DocumentAnalyzer()
        return self._doc_analyzer
    
    @property
    def cmd_analyzer(self) -> CommandAnalyzer:
        if self._cmd_analyzer is None:
            self._cmd_analyzer = CommandAnalyzer()
        return self._cmd_analyzer
    
    @property
    def qwen(self) -> Optional[QwenDocumentGenerator]:
        """Inicializa Qwen apenas se usar_qwen=True e disponível"""
        if not self.config.usar_qwen:
            return None
        
        if not QWEN_AVAILABLE:
            logger.warning("⚠️ Qwen não disponível (instale qwen_integration)")
            return None
        
        if self._qwen is None:
            try:
                backend = LlamaBackend.SERVER if self.config.qwen_backend == "server" else LlamaBackend.PYTHON
                qwen_config = LlamaConfig(
                    backend=backend,
                    server_url=self.config.qwen_server_url,
                    model_path=self.config.qwen_model_path
                )
                self._qwen = QwenDocumentGenerator(qwen_config)
                logger.info("✅ Qwen 2.5 inicializado")
            except Exception as e:
                logger.warning(f"⚠️ Erro ao inicializar Qwen: {e}")
                return None
        return self._qwen
    
    @property
    def email_sender(self) -> EmailSender:
        if self._email_sender is None:
            email_config = EmailConfig(
                remetente=self.config.email_remetente,
                senha_app=self.config.email_senha_app
            )
            self._email_sender = EmailSender(email_config)
        return self._email_sender
    
    @property
    def juntada(self) -> ProjudiJuntada:
        if self._juntada is None:
            projudi_config = ProjudiConfig(
                link_base=self.config.projudi_link_base,
                codigo_juntada=self.config.projudi_codigo_juntada
            )
            cookies = self.bot.exportar_cookies()
            self._juntada = ProjudiJuntada(projudi_config, cookies)
        return self._juntada
    
    @property
    def processor(self) -> OficioProcessor:
        if self._processor is None:
            self._protocolo = ProtocoloCSV(self.config.protocolo_csv_path)
            self._extractor = OficioExtractor()
            self._processor = OficioProcessor(
                self.email_sender,
                self.juntada,
                self._protocolo
            )
        return self._processor
    
    @property
    def protocolo(self) -> ProtocoloCSV:
        if self._protocolo is None:
            self._protocolo = ProtocoloCSV(self.config.protocolo_csv_path)
        return self._protocolo
    
    # -------------------------------------------------------------------------
    # FLUXO PRINCIPAL
    # -------------------------------------------------------------------------
    
    def executar_pipeline_completo(self) -> List[PipelineResult]:
        """
        Executa o pipeline completo:
        1. Lista movimentações pendentes
        2. Para cada uma, processa até o fim
        """
        self._running = True
        self._results = []
        
        logger.info("=" * 80)
        logger.info("INICIANDO PIPELINE DE CUMPRIMENTO JUDICIAL")
        logger.info("=" * 80)
        
        try:
            # Passo 1: Listar movimentações pendentes
            movimentacoes = self._listar_movimentacoes_pendentes()
            logger.info(f"📋 {len(movimentacoes)} movimentações pendentes encontradas")
            
            # Passo 2: Processar cada movimentação
            for i, mov in enumerate(movimentacoes, 1):
                if not self._running:
                    logger.info("⏹ Pipeline interrompido pelo usuário")
                    break
                
                logger.info(f"\n{'='*80}")
                logger.info(f"PROCESSANDO {i}/{len(movimentacoes)}: {mov['processo']}")
                logger.info(f"{'='*80}")
                
                result = self._processar_movimentacao(mov)
                self._results.append(result)
                
                # Delay entre processamentos
                self._human_delay()
            
            # Resumo final
            self._log_resumo()
            
        except Exception as e:
            logger.error(f"❌ Erro no pipeline: {e}")
        
        finally:
            self._running = False
            self.cleanup()
        
        return self._results
    
    def _listar_movimentacoes_pendentes(self) -> List[Dict]:
        """Lista movimentações pendentes de análise"""
        
        session = self.bot.session
        url = self.client.URL_MOVIMENTACOES
        
        response = session.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extrai links usando método do ProjudiClient
        itens = self.client.extrair_links_movimentacoes(soup)
        
        # Filtra apenas os que têm documento para analisar
        pendentes = [
            item for item in itens
            if item.get('link_documento') and item.get('movimentar')
        ]
        
        return pendentes
    
    def _processar_movimentacao(self, mov: Dict) -> PipelineResult:
        """Processa uma movimentação individual"""
        
        result = PipelineResult(
            processo=mov['processo'],
            tipo=mov.get('tipo', 'desconhecido')
        )
        
        try:
            # ── PASSO 1: Extrair texto do documento ──
            result.status = PipelineStatus.EM_ANALISE
            logger.info(f"📄 Extraindo texto do documento...")
            
            texto_documento = self._extrair_texto_documento(mov)
            
            if not texto_documento:
                result.status = PipelineStatus.FALHOU
                result.erro = "Não foi possível extrair texto do documento"
                return result
            
            # ── PASSO 2: Analisar comandos judiciais ──
            logger.info(f"🔍 Analisando comandos judiciais...")
            comandos = self._analisar_comandos(texto_documento, mov)
            result.comandos = comandos
            result.status = PipelineStatus.COMANDOS_EXTRAIDOS
            
            if not comandos:
                logger.info("ℹ️ Nenhum comando judicial extraído")
                result.status = PipelineStatus.DISPENSADO
                return result
            
            logger.info(f"✅ {len(comandos)} comando(s) extraído(s)")
            
            # Callback
            if self.config.on_command_extracted:
                self.config.on_command_extracted(result)
            
            # ── PASSO 3: Buscar padrões similares (RAG) ──
            cumprimentos_similares = []
            if self.config.usar_rag and self._rag_pipeline:
                logger.info(f"🔎 Buscando padrões similares (RAG)...")
                cumprimentos_similares = self._buscar_similares(comandos)
            
            # ── PASSO 4: Qwen sugere plano (OPCIONAL) ──
            plano = None
            if self.config.usar_qwen and self.config.usar_qwen_plano:
                logger.info(f"🤖 Qwen gerando plano de cumprimento...")
                plano = self._qwen_sugerir_plano(
                    comandos, texto_documento, mov, cumprimentos_similares
                )
                result.plano_sugerido = plano
                if plano:
                    result.status = PipelineStatus.PLANO_GERADO
            
            # Callback
            if self.config.on_plan_generated:
                self.config.on_plan_generated(result)
            
            # ── PASSO 5: Aprovação (se não for auto) ──
            if not self.config.auto_executar:
                aprovar = self._solicitar_aprovacao(result)
                if not aprovar:
                    result.status = PipelineStatus.DISPENSADO
                    return result
            
            # ── PASSO 6: Executar cumprimento ──
            result.status = PipelineStatus.EM_EXECUCAO
            logger.info(f"⚡ Executando cumprimento...")
            
            self._executar_cumprimento(result, mov, texto_documento)
            
            # ── PASSO 7: Verificação de consistência (OPCIONAL) ──
            if self.config.usar_qwen and self.config.usar_qwen_verificacao and result.email_enviado:
                logger.info(f"🔍 Qwen verificando consistência...")
                verificacao = self._qwen_verificar(result, texto_documento)
                result.verificacao_consistencia = verificacao
            
            # ── PASSO 8: Finalizar ──
            if result.email_enviado and result.juntada_realizada:
                result.status = PipelineStatus.CONCLUIDO
                logger.info(f"✅ Cumprimento concluído com sucesso!")
            elif result.email_enviado:
                result.status = PipelineStatus.CONCLUIDO
                logger.info(f"⚠️ Email enviado, mas juntada pendente")
            else:
                result.status = PipelineStatus.FALHOU
                logger.info(f"❌ Cumprimento não realizado")
            
        except Exception as e:
            result.status = PipelineStatus.FALHOU
            result.erro = str(e)
            logger.error(f"❌ Erro ao processar {mov['processo']}: {e}")
        
        return result
    
    # -------------------------------------------------------------------------
    # ETAPAS DO PIPELINE
    # -------------------------------------------------------------------------
    
    def _extrair_texto_documento(self, mov: Dict) -> Optional[str]:
        """Extrai texto do documento HTML"""
        
        session = self.bot.session
        link_doc = mov.get('link_documento')
        
        if not link_doc:
            return None
        
        try:
            response = session.get(link_doc)
            response.raise_for_status()
            
            texto = self.doc_analyzer.extrair_texto_documento(response.text)
            texto = self.doc_analyzer.limpar_texto(texto)
            
            return texto
            
        except Exception as e:
            logger.error(f"Erro ao extrair texto: {e}")
            return None
    
    def _analisar_comandos(self, texto: str, mov: Dict) -> List[Dict]:
        """Analisa comandos judiciais no texto"""
        
        try:
            # Usa DocumentAnalyzer para extrair comandos estruturados
            resultado = self.doc_analyzer.analisar_movimentacao(
                texto,  # Já é o texto limpo
                mov
            )
            
            comandos_dict = resultado.get('comandos', [])
            
            # Converte para lista de comandos
            comandos = []
            if isinstance(comandos_dict, list):
                for cmd in comandos_dict:
                    comandos.append({
                        'comando': cmd.get('comando', ''),
                        'meio': cmd.get('meio', []),
                        'quando': cmd.get('quando', []),
                        'condicao': cmd.get('condicao', []),
                        'prazo': cmd.get('prazo'),
                    })
            
            return comandos
            
        except Exception as e:
            logger.error(f"Erro ao analisar comandos: {e}")
            return []
    
    def _buscar_similares(self, comandos: List[Dict]) -> List[Dict]:
        """Busca cumprimentos similares via RAG"""
        
        if not self._rag_pipeline:
            return []
        
        similares = []
        for cmd in comandos:
            texto = cmd.get('comando', '')
            if texto:
                results = self._rag_pipeline.find_successful_compliances_by_text(
                    texto, top_k=3
                )
                similares.extend(results)
        
        return similares
    
    def _qwen_sugerir_plano(
        self,
        comandos: List[Dict],
        texto_documento: str,
        mov: Dict,
        cumprimentos_similares: List[Dict]
    ) -> Optional[Dict]:
        """Usa Qwen para sugerir plano de cumprimento (OPCIONAL)"""
        
        # Verifica se Qwen está habilitado e disponível
        if not self.config.usar_qwen_plano:
            return None
        
        if self.qwen is None:
            return None
        
        try:
            comando_texto = "\n".join([
                c.get('comando', '') for c in comandos
            ])
            
            dados_processo = {
                'numero': mov.get('processo', ''),
                'partes': [],
            }
            
            plano = self.qwen.sugerir_plano_cumprimento(
                comando_judicial=comando_texto,
                dados_processo=dados_processo,
                cumprimentos_similares=cumprimentos_similares
            )
            
            return plano
            
        except Exception as e:
            logger.warning(f"Qwen não disponível para sugestão: {e}")
            return None
    
    def _qwen_verificar(
        self,
        result: PipelineResult,
        texto_documento: str
    ) -> Optional[Dict]:
        """Usa Qwen para verificar consistência (OPCIONAL)"""
        
        # Verifica se Qwen está habilitado e disponível
        if not self.config.usar_qwen_verificacao:
            return None
        
        if self.qwen is None:
            return None
        
        try:
            comando_texto = "\n".join([
                c.get('comando', '') for c in result.comandos
            ])
            
            cumprimento_desc = f"""
            Processo: {result.processo}
            Email enviado: {'Sim' if result.email_enviado else 'Não'}
            Juntada realizada: {'Sim' if result.juntada_realizada else 'Não'}
            """
            
            verificacao = self.qwen.verificar_consistencia(
                comando_judicial=comando_texto,
                cumprimento_realizado=cumprimento_desc,
                contexto_processo={'numero': result.processo}
            )
            
            return verificacao
            
        except Exception as e:
            logger.warning(f"Qwen não disponível para verificação: {e}")
            return None
    
    def _executar_cumprimento(
        self,
        result: PipelineResult,
        mov: Dict,
        texto_documento: str
    ):
        """Executa o cumprimento (email + juntada)"""
        
        # Callback antes de executar
        if self.config.on_before_execute:
            self.config.on_before_execute(result)
        
        try:
            # Extrai dados do ofício do texto
            session = self.bot.session
            
            # Busca URL do ofício (se for cumprimento de cartório)
            url_oficio = self._buscar_url_oficio(mov)
            
            if url_oficio:
                # Busca HTML do ofício
                response = session.get(url_oficio)
                
                # Extrai dados usando OficioExtractor
                oficio_data = self._extractor.extrair_de_html(
                    response.text,
                    mov['processo'],
                    {
                        'url_oficio': url_oficio,
                        'url_processo': mov.get('link_processo', ''),
                        'url_recebimento': mov.get('movimentar', ''),
                        'url_baixa': '',
                    }
                )
                
                if oficio_data:
                    # Processa ofício (envia email + juntada)
                    resultado_proc = self.processor.processar(oficio_data)
                    
                    result.email_enviado = resultado_proc.get('email_enviado', False)
                    result.juntada_realizada = resultado_proc.get('juntada_realizada', False)
                    
                    if resultado_proc.get('erro'):
                        result.erro = resultado_proc['erro']
                else:
                    # Fallback: tenta juntada direta
                    self._juntada_direta(result, mov, texto_documento)
            else:
                # Sem URL de ofício, tenta juntada direta
                self._juntada_direta(result, mov, texto_documento)
                
        except Exception as e:
            logger.error(f"Erro ao executar cumprimento: {e}")
            result.erro = str(e)
    
    def _buscar_url_oficio(self, mov: Dict) -> Optional[str]:
        """Busca URL do ofício se disponível"""
        
        # Se a movimentação tem link direto para cumprimento
        if 'link_documento' in mov:
            return mov['link_documento']
        
        return None
    
    def _juntada_direta(
        self,
        result: PipelineResult,
        mov: Dict,
        texto_documento: str
    ):
        """Realiza juntada direta sem envio de email"""
        
        url_recebimento = mov.get('movimentar', '')
        
        if not url_recebimento:
            result.erro = "URL de recebimento não disponível"
            return
        
        observacao = f"Análise automática realizada em {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        
        sucesso = self.juntada.realizar_juntada(
            url_recebimento=url_recebimento,
            codigo_movimentacao=self.config.projudi_codigo_juntada,
            observacao=observacao
        )
        
        if sucesso:
            result.juntada_realizada = True
    
    def _solicitar_aprovacao(self, result: PipelineResult) -> bool:
        """Solicita aprovação do usuário"""
        
        print(f"\n{'='*60}")
        print(f"PROCESSO: {result.processo}")
        print(f"TIPO: {result.tipo}")
        print(f"{'='*60}")
        
        if result.comandos:
            print(f"\n📋 COMANDOS EXTRAÍDOS ({len(result.comandos)}):")
            for i, cmd in enumerate(result.comandos, 1):
                print(f"  {i}. {cmd.get('comando', 'N/A')[:100]}...")
        
        if result.plano_sugerido:
            plano = result.plano_sugerido.get('plano_sugerido', {})
            print(f"\n🤖 PLANO SUGERIDO PELO QWEN:")
            print(f"  Tipo: {plano.get('tipo_acao', 'N/A')}")
            print(f"  Descrição: {plano.get('descricao', 'N/A')}")
            passos = plano.get('passos', [])
            if passos:
                print(f"  Passos:")
                for p in passos:
                    print(f"    - {p}")
        
        print(f"\n{'='*60}")
        resposta = input("Executar cumprimento? [s/N/q(sair)]: ").strip().lower()
        
        if resposta == 'q':
            self._running = False
            return False
        
        return resposta in ('s', 'sim', 'y', 'yes')
    
    # -------------------------------------------------------------------------
    # UTILITÁRIOS
    # -------------------------------------------------------------------------
    
    def _human_delay(self):
        """Delay aleatório entre requisições"""
        delay = random.uniform(self.config.delay_min, self.config.delay_max)
        time.sleep(delay)
    
    def _log_resumo(self):
        """Log do resumo do pipeline"""
        
        total = len(self._results)
        concluidos = sum(1 for r in self._results if r.status == PipelineStatus.CONCLUIDO)
        falharam = sum(1 for r in self._results if r.status == PipelineStatus.FALHOU)
        dispensados = sum(1 for r in self._results if r.status == PipelineStatus.DISPENSADO)
        
        logger.info("\n" + "=" * 80)
        logger.info("RESUMO DO PIPELINE")
        logger.info("=" * 80)
        logger.info(f"Total processado: {total}")
        logger.info(f"✅ Concluídos: {concluidos}")
        logger.info(f"❌ Falharam: {falharam}")
        logger.info(f"⏭ Dispensados: {dispensados}")
        logger.info("=" * 80)
    
    def cleanup(self):
        """Limpa recursos"""
        if self._juntada:
            self._juntada.close()
        logger.info("🧹 Recursos liberados")
    
    def parar(self):
        """Para o pipeline"""
        self._running = False


# =============================================================================
# EXEMPLO DE USO
# =============================================================================

def main():
    """Exemplo de uso do pipeline"""
    
    # Configuração - Qwen é OPCIONAL
    config = PipelineConfig(
        email_remetente='pafonso.2vsj@gmail.com',
        email_senha_app='ouysuorpvqprfqig',
        
        # Qwen - DESABILITADO por padrão (nem todos os cumprimentos precisam)
        usar_qwen=False,  # Ative apenas se quiser usar Qwen
        usar_qwen_plano=False,  # Gerar plano com Qwen
        usar_qwen_verificacao=False,  # Verificar consistência com Qwen
        
        # Qwen config (só usa se usar_qwen=True)
        qwen_backend="server",  # "server" ou "python"
        qwen_server_url="http://localhost:8080",
        
        # Comportamento
        auto_executar=False,  # Pede aprovação antes de executar
        usar_rag=False,  # Ativar quando pgvector estiver configurado
    )
    
    # Callbacks opcionais
    def on_command_extracted(result: PipelineResult):
        print(f"\n📋 Comandos extraídos de {result.processo}:")
        for cmd in result.comandos:
            print(f"   - {cmd.get('comando', '')[:80]}")
    
    def on_plan_generated(result: PipelineResult):
        if result.plano_sugerido:
            plano = result.plano_sugerido.get('plano_sugerido', {})
            print(f"\n🤖 Plano sugerido: {plano.get('tipo_acao', 'N/A')}")
    
    config.on_command_extracted = on_command_extracted
    config.on_plan_generated = on_plan_generated
    
    # Cria e executa pipeline
    pipeline = PipelineOrchestrator(config)
    
    try:
        results = pipeline.executar_pipeline_completo()
        
        # Processa resultados
        for r in results:
            print(f"\n{r.processo}: {r.status.value}")
            if r.erro:
                print(f"  Erro: {r.erro}")
    
    except KeyboardInterrupt:
        print("\n⏹ Pipeline interrompido pelo usuário")
        pipeline.parar()
    
    except Exception as e:
        print(f"\n❌ Erro: {e}")


if __name__ == "__main__":
    main()
