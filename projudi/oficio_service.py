"""
OficioService - Orquestra busca, envio, juntada e logging de oficios.

Integra:
- ProjudiService (sessao via cookies salvos -> acesso direto ao link de oficios)
- exemplo_refatoracao_oo (EmailSender, ProjudiJuntada, OficioExtractor, ProtocoloCSV)
- Models Django (OficioRecord, OficioLog)

Fluxo (copiado do pipeline legado):
1. Pega cookies salvos no Django (ProjudiSession)
2. Vai direto no link de oficios (sem novo login)
3. Navega ate a ultima pagina e pega as 3 ultimas paginas
4. Para cada oficio:
   a) Extrai dados (numero, email, processo, URLs)
   b) Salva no banco (OficioRecord)
   c) Tenta enviar e-mail
   d) Se enviar ok -> juntada de cumprimento
   e) Se falhar e-mail -> gera resposta de impossibilidade e junta no processo
   f) Tudo e logado de forma humanizada (OficioLog)
"""

import sys
import re
import time
import traceback
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from django.conf import settings
from django.utils import timezone

PROJECT_ROOT = str(settings.BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from exemplo_refatoracao_oo import (
    EmailConfig, EmailSender,
    ProjudiConfig, ProjudiJuntada,
    OficioExtractor, OficioData,
    ProtocoloCSV,
)
from projudi_client import ProjudiClient

from .models import OficioRecord, OficioLog
from .services import ProjudiService


class OficioService:
    """Servico de orquestracao de oficios judiciais."""

    def __init__(self, user):
        self.user = user
        self.projudi_service = ProjudiService(user)
        self.extractor = OficioExtractor()
        self._email_sender = None
        self._juntada = None
        self._protocolo = None

    # ------------------------------------------------------------------
    # LAZY INIT
    # ------------------------------------------------------------------
    @property
    def email_sender(self) -> EmailSender:
        if self._email_sender is None:
            cfg = EmailConfig(
                remetente=getattr(settings, 'EMAIL_HOST_USER', 'pafonso.2vsj@gmail.com'),
                senha_app=getattr(settings, 'EMAIL_HOST_PASSWORD', ''),
            )
            self._email_sender = EmailSender(cfg)
        return self._email_sender

    @property
    def juntada(self) -> ProjudiJuntada:
        if self._juntada is None:
            cookies = self.projudi_service.get_cookies()
            cfg = ProjudiConfig()
            self._juntada = ProjudiJuntada(cfg, cookies)
        return self._juntada

    @property
    def protocolo(self) -> ProtocoloCSV:
        if self._protocolo is None:
            self._protocolo = ProtocoloCSV()
        return self._protocolo

    # ------------------------------------------------------------------
    # BUSCA  (cookies salvos -> link direto -> ultima pagina -> 3 ultimas)
    # ------------------------------------------------------------------
    def buscar_oficios_pendentes(self, quantidade: int = 3) -> List[Dict]:
        """
        Usa ProjudiService.list_oficios() que:
         - pega cookies salvos no Django
         - acessa URL_OFICIOS diretamente
         - descobre ultima pagina
         - retorna as N ultimas paginas (padrao 3)
        Retorna lista de dicts: processo, url_oficio, url_processo, url_recebimento, url_baixa.
        """
        return self.projudi_service.list_oficios(quantidade=quantidade)

    def extrair_oficio(self, dados: Dict) -> Optional[OficioData]:
        """
        Faz GET no URL do oficio e extrai dados estruturados via OficioExtractor.
        Usa a session do ProjudiService (cookies salvos).
        """
        result = self.projudi_service._get_session_from_cookies()
        if result is None:
            # Fallback: inicializa bot + client do zero
            client = self.projudi_service.get_client()
            client.iniciar()
            session = client.session
        else:
            session, _ = result

        url_oficio = dados.get('url_oficio')
        if not url_oficio:
            return None

        resp = session.get(url_oficio)
        if resp.status_code != 200:
            return None

        return self.extractor.extrair_de_html(
            html=resp.text,
            processo=dados.get('processo', ''),
            urls={
                'url_oficio': dados.get('url_oficio', ''),
                'url_processo': dados.get('url_processo', ''),
                'url_recebimento': dados.get('url_recebimento', ''),
                'url_baixa': dados.get('url_baixa', ''),
            },
            processo_cnj=dados.get('processo_cnj', '')
        )

    # ------------------------------------------------------------------
    # PERSISTENCIA
    # ------------------------------------------------------------------
    def importar_oficio(self, oficio_data: OficioData) -> OficioRecord:
        """Cria ou atualiza OficioRecord no banco a partir de OficioData."""
        # Extrai numero CNJ dos dados brutos (se disponivel)
        processo_cnj = getattr(oficio_data, 'processo_cnj', '') or ''
        
        # Remove status dos defaults — NUNCA sobrescrever status existente.
        # A sincronização não pode resetar 'enviado'/'juntado'/'dispensado' para 'pendente'.
        record, created = OficioRecord.objects.update_or_create(
            processo=oficio_data.processo,
            numero_oficio=oficio_data.numero_oficio,
            defaults={
                'numero_processo_cnj': processo_cnj,
                'email_destino': oficio_data.email_destino,
                'assunto': oficio_data.assunto,
                'url_oficio': oficio_data.url_oficio,
                'url_processo': oficio_data.url_processo,
                'url_recebimento': oficio_data.url_recebimento,
                'url_baixa': oficio_data.url_baixa,
                'texto_html': oficio_data.texto_html,
                'user': self.user,
            }
        )

        if created:
            # Só seta como pendente se for um ofício NOVO (nunca visto antes)
            record.status = 'pendente'
            record.save(update_fields=['status'])
            self._log(record, 'info',
                f"Oficio {oficio_data.numero_oficio} importado do Projudi e aguardando envio.",
                {'acao': 'importacao'}
            )
        else:
            # Preserva o status original — se já foi enviado/dispensado, continua assim
            self._log(record, 'info',
                f"Oficio {oficio_data.numero_oficio} atualizado com novos dados do Projudi "
                f"(status mantido: {record.status}).",
                {'acao': 'atualizacao'}
            )

        return record

    # ------------------------------------------------------------------
    # ENVIO
    # ------------------------------------------------------------------
    def enviar_email(self, record: OficioRecord) -> Tuple[bool, str]:
        """Tenta enviar o oficio por e-mail. Retorna (sucesso, msg_id_ou_erro)."""
        if not record.email_destino:
            msg = "Impossivel enviar: nenhum e-mail de destino encontrado no oficio."
            self._log(record, 'erro_email', msg, {'etapa': 'validacao'})
            return False, msg

        oficio = OficioData(
            processo=record.processo,
            numero_oficio=record.numero_oficio,
            email_destino=record.email_destino,
            url_oficio=record.url_oficio,
            url_processo=record.url_processo,
            url_recebimento=record.url_recebimento,
            url_baixa=record.url_baixa,
            texto_html=record.texto_html,
            assunto=record.assunto,
            processo_cnj=record.numero_processo_cnj,
        )

        try:
            sucesso, msg_id = self.email_sender.enviar_oficio(oficio)
        except Exception as e:
            sucesso = False
            msg_id = str(e)

        if sucesso:
            record.status = 'enviado'
            record.msg_id = msg_id
            now = datetime.now()
            record.data_envio = now.date()
            record.hora_envio = now.time()
            record.save()

            self._log(record, 'envio',
                f"E-mail enviado com sucesso para {record.email_destino} em "
                f"{record.data_envio.strftime('%d/%m/%Y')} as {record.hora_envio.strftime('%H:%M')}.",
                {'msg_id': msg_id, 'destino': record.email_destino}
            )

            # Registra no CSV legado
            try:
                self.protocolo.registrar_envio(
                    oficio, msg_id,
                    record.data_envio.strftime('%d/%m/%Y'),
                    record.hora_envio.strftime('%H:%M:%S')
                )
            except Exception:
                pass

            return True, msg_id
        else:
            record.status = 'falhou_email'
            record.save()

            # Log humanizado do erro
            erro_humanizado = self.humanizar_erro(msg_id)
            self._log(record, 'erro_email',
                f"{erro_humanizado} O sistema tentara gerar uma resposta de impossibilidade de cumprimento no processo.",
                {'erro_tecnico': msg_id, 'etapa': 'smtp'}
            )
            return False, msg_id

    # ------------------------------------------------------------------
    # JUNTADA VIA REQUESTS (sem Selenium - usando mesma sessao do usuario)
    # ------------------------------------------------------------------
    def juntar_cumprimento(self, record: OficioRecord) -> bool:
        """Realiza juntada de cumprimento via requests (mesma sessao do usuario)."""
        if not record.url_recebimento:
            self._log(record, 'erro_juntada',
                "Impossivel juntar: URL de recebimento nao disponivel.",
                {'etapa': 'validacao'}
            )
            return False

        try:
            sucesso, motivo, snippet = self._juntar_via_requests(record)
            if sucesso:
                record.status = 'juntado'
                record.save()
                self.protocolo.atualizar_juntada(record.processo, record.numero_oficio)
                self._log(record, 'juntada',
                    f"Juntada realizada no Projudi. Oficio {record.numero_oficio} cumprido.",
                    {'etapa': 'cumprimento', 'motivo_sucesso': motivo}
                )
                return True
            else:
                self._log(record, 'erro_juntada',
                    f"Juntada recusada pelo Projudi: {motivo}",
                    {'etapa': 'cumprimento', 'motivo_falha': motivo, 'snippet': snippet[:300]}
                )
        except Exception as e:
            self._log(record, 'erro_juntada',
                f"Erro tecnico na juntada: {str(e)[:100]}",
                {'etapa': 'cumprimento', 'erro': str(e)}
            )
        
        record.status = 'falhou_juntada'
        record.save()
        return False

    def _juntar_via_requests(self, record: OficioRecord, codigo_movimentacao: str = '11383', observacao: str = None) -> Tuple[bool, str, str]:
        """
        Juntada via requests usando multipart/form-data (exigido pelo Projudi).
        Tenta codigo 11383 (Cumprimento de Oficio) primeiro,
        fallback para 581 (TD - Tipo Documental) se necessario.
        """
        from bs4 import BeautifulSoup
        import time

        # 1. Pega sessao com cookies
        result = self.projudi_service._get_session_from_cookies()
        if result is None:
            raise Exception("Sessao nao disponivel")
        session, _ = result

        # 2. Acessa pagina de recebimento
        resp = session.get(record.url_recebimento, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")

        if 'login' in resp.url.lower():
            raise Exception("Sessao expirada - redirecionado para login")

        # 3. Parse do form
        soup = BeautifulSoup(resp.text, 'html.parser')
        form = soup.find('form')
        if not form:
            raise Exception("Formulario nao encontrado")

        action = form.get('action', '')
        if action.startswith('/'):
            post_url = f"https://projudi.tjba.jus.br{action}"
        elif action.startswith('http'):
            post_url = action
        else:
            post_url = record.url_recebimento

        # 4. Monta payload base (todos campos do formulario)
        payload = {}

        for inp in form.find_all('input'):
            typ = inp.get('type', '')
            name = inp.get('name')
            if not name:
                continue
            if typ == 'checkbox':
                if inp.get('checked') is not None and name != 'codParteTransPenal':
                    payload[name] = inp.get('value', '')
            elif typ == 'radio':
                if inp.get('checked') is not None:
                    payload[name] = inp.get('value', '')
            elif typ in ('hidden', 'text', 'email', 'tel', 'number', 'date', ''):
                val = inp.get('value', '')
                if val or typ == 'hidden':
                    payload[name] = val

        for sel in form.find_all('select'):
            name = sel.get('name')
            if not name:
                continue
            selected = sel.find('option', selected=True)
            val = selected.get('value', '') if selected else ''
            if val and val not in ('-1', '0'):
                payload[name] = val
            elif name in ('acaoCodTipoLocalizador',):
                payload[name] = val

        for ta in form.find_all('textarea'):
            name = ta.get('name')
            if name:
                payload[name] = ta.get_text()

        # 5. Botao Concluir (image submit envia x e y)
        payload['Concluir.x'] = '10'
        payload['Concluir.y'] = '10'

        # 6. Observacao (personalizada ou padrao)
        if observacao is None:
            data_envio = record.data_envio.strftime('%d/%m/%Y') if record.data_envio else ''
            hora_envio = record.hora_envio.strftime('%H:%M') if record.hora_envio else ''
            observacao = (
                f"Oficio - n {record.numero_oficio} - "
                f"E-mail enviado com sucesso para {record.email_destino} "
                f"em {data_envio} as {hora_envio}. "
                f"Link do oficio: {record.url_oficio}"
            )
        payload['observacao'] = observacao
        payload['observacaoDiligencia'] = ''

        # 7. Remove campos que criam movimentacoes indesejadas (delegacia, etc.)
        campos_indesejados = [
            'codDelegacia', 'codPrazoEnviaDelegacia',
            'enviaDelegacia', 'enviaMP', 'enviaTurmaRecursal',
            'enviaCartorioExtrajudicial', 'arquivar',
            'psicossocial', 'contador',
        ]
        for campo in campos_indesejados:
            payload.pop(campo, None)

        # 8. Codigo da movimentacao
        payload['seqCategoriaMovimentacao'] = codigo_movimentacao
        if codigo_movimentacao == '11383':
            payload['descCategoriaMovimentacao'] = 'Cumprimento de Oficio'
        else:
            payload['descCategoriaMovimentacao'] = 'TD - Tipo Documental'

        # Remove duplicatas de codTipoLocalizador
        if isinstance(payload.get('codTipoLocalizador'), list):
            payload['codTipoLocalizador'] = payload['codTipoLocalizador'][-1]

        # 9. Envia como multipart/form-data (exigido pelo Projudi)
        time.sleep(1)
        multipart_data = {k: (None, str(v).encode('latin-1', errors='replace')) for k, v in payload.items()}
        resp_post = session.post(post_url, files=multipart_data, timeout=15)

        # 10. Verifica se deu certo
        sucesso, motivo, snippet = self._verificar_sucesso_juntada(resp_post)

        if not sucesso and codigo_movimentacao == '11383':
            # Fallback para 581
            self._log(record, 'info',
                f"Codigo 11383 (Cumprimento de Oficio) nao funcionou. Motivo: {motivo}. Tentando codigo 581 (TD)...",
                {'etapa': 'fallback_codigo', 'motivo_falha': motivo, 'snippet': snippet[:200]}
            )
            payload['seqCategoriaMovimentacao'] = '581'
            payload['descCategoriaMovimentacao'] = 'TD - Tipo Documental'
            multipart_data = {k: (None, str(v).encode('latin-1', errors='replace')) for k, v in payload.items()}
            time.sleep(1)
            resp_post = session.post(post_url, files=multipart_data, timeout=15)
            sucesso, motivo, snippet = self._verificar_sucesso_juntada(resp_post)

        return sucesso, motivo, snippet

    def _verificar_sucesso_juntada(self, resp_post) -> Tuple[bool, str, str]:
        """
        Verifica se a juntada foi realmente processada.
        Retorna: (sucesso: bool, motivo: str, snippet_html: str)
        """
        from bs4 import BeautifulSoup

        snippet = resp_post.text[:800]

        # 1. HTTP nao 200
        if resp_post.status_code != 200:
            return False, f"HTTP {resp_post.status_code}", snippet

        # 2. Redirecionado para login
        if 'login' in resp_post.url.lower():
            return False, "Redirecionado para login (sessao expirada)", snippet

        # 3. Mensagem de erro explicita no HTML
        texto_lower = resp_post.text.lower()
        if 'ocorreu um erro' in texto_lower:
            return False, "Pagina contem 'ocorreu um erro'", snippet
        if 'erro não definido' in texto_lower or 'erro nao definido' in texto_lower:
            return False, "Pagina contem 'erro nao definido'", snippet

        # 4. Erro de multipart antigo
        if "doesn't contain a multipart/form-data" in resp_post.text:
            return False, "Erro de multipart/form-data no servidor", snippet

        soup = BeautifulSoup(resp_post.text, 'html.parser')

        # 5. Se ainda contem o formulario MovimentarProcesso -> provavelmente ficou na mesma pagina
        form = soup.find('form')
        if form and 'MovimentarProcesso' in str(form.get('action', '')):
            # Tentar achar mensagem de validacao no HTML
            alertas = soup.find_all(string=re.compile(r'obrigatório|obrigatorio|preenchimento|campo|inválido|invalido', re.I))
            if alertas:
                return False, f"Formulario ainda presente (validacao: {alertas[0].strip()[:60]})", snippet
            return False, "Formulario MovimentarProcesso ainda presente (nao processou)", snippet

        # 6. CRITERIOS POSITIVOS de sucesso
        # Se redirectou para DadosProcesso ou Historico -> sucesso
        if 'DadosProcesso' in resp_post.url or 'Historico' in resp_post.url:
            return True, "Redirect para pagina do processo", snippet

        # Se contem mensagem de confirmacao/sucesso
        confirmacoes = [
            'movimentação incluída', 'movimentacao incluida',
            'operação realizada', 'operacao realizada',
            'dados gravados', 'registro incluido',
        ]
        for conf in confirmacoes:
            if conf in texto_lower:
                return True, f"Mensagem de confirmacao encontrada: '{conf}'", snippet

        # 7. Se nao achou formulario e nao achou erro -> assume sucesso (redirect ou pagina de confirmacao)
        # mas loga pra gente poder melhorar depois
        return True, "Nenhum formulario nem erro detectado (assumindo sucesso)", snippet

    def juntar_resposta_impossibilidade(self, record: OficioRecord, motivo: str = "") -> bool:
        """
        Quando nao e possivel enviar o oficio por e-mail, gera uma
        'resposta de impossibilidade' e junta no processo.
        """
        if not record.url_recebimento:
            self._log(record, 'erro_juntada',
                "Impossivel juntar resposta: URL de recebimento nao disponivel.",
                {'etapa': 'validacao_resposta'}
            )
            return False

        try:
            # Mesmo processo de juntada, mas com observacao de impossibilidade
            observacao = self._gerar_texto_impossibilidade(record, motivo)
            
            result = self.projudi_service._get_session_from_cookies()
            if result is None:
                raise Exception("Sessao nao disponivel")
            session, _ = result

            from bs4 import BeautifulSoup
            import time

            resp = session.get(record.url_recebimento, timeout=15)
            if resp.status_code != 200 or 'login' in resp.url.lower():
                raise Exception("Sessao expirada")

            soup = BeautifulSoup(resp.text, 'html.parser')
            form = soup.find('form')
            if not form:
                raise Exception("Formulario nao encontrado")

            action = form.get('action', '')
            post_url = f"https://projudi.tjba.jus.br{action}" if action.startswith('/') else record.url_recebimento

            payload = {}
            for inp in form.find_all('input', {'type': 'hidden'}):
                name = inp.get('name')
                if name:
                    payload[name] = inp.get('value', '')
            for inp in form.find_all('input', {'type': 'checkbox'}):
                name = inp.get('name')
                if name and inp.get('checked') is not None:
                    if name != 'codParteTransPenal':
                        payload[name] = inp.get('value', '')
            for sel in form.find_all('select'):
                name = sel.get('name')
                if not name:
                    continue
                selected = sel.find('option', selected=True)
                val = selected.get('value', '') if selected else ''
                if val and val not in ('-1', '0'):
                    payload[name] = val
            for ta in form.find_all('textarea'):
                name = ta.get('name')
                if name:
                    payload[name] = ta.get_text()

            payload['Concluir.x'] = '10'
            payload['Concluir.y'] = '10'
            payload['seqCategoriaMovimentacao'] = '11383'
            payload['descCategoriaMovimentacao'] = 'Cumprimento de Oficio'
            payload['observacao'] = observacao
            payload['observacaoDiligencia'] = ''

            # Remove campos indesejados
            campos_indesejados = [
                'codDelegacia', 'codPrazoEnviaDelegacia',
                'enviaDelegacia', 'enviaMP', 'enviaTurmaRecursal',
                'enviaCartorioExtrajudicial', 'arquivar',
                'psicossocial', 'contador',
            ]
            for campo in campos_indesejados:
                payload.pop(campo, None)

            if isinstance(payload.get('codTipoLocalizador'), list):
                payload['codTipoLocalizador'] = payload['codTipoLocalizador'][-1]

            multipart_data = {k: (None, str(v).encode('latin-1', errors='replace')) for k, v in payload.items()}
            time.sleep(1)
            resp_post = session.post(post_url, files=multipart_data, timeout=15)
            
            sucesso, motivo_v, snippet_v = self._verificar_sucesso_juntada(resp_post)
            
            if not sucesso:
                # Fallback 581
                payload['seqCategoriaMovimentacao'] = '581'
                payload['descCategoriaMovimentacao'] = 'TD - Tipo Documental'
                multipart_data = {k: (None, str(v).encode('latin-1', errors='replace')) for k, v in payload.items()}
                time.sleep(1)
                resp_post = session.post(post_url, files=multipart_data, timeout=15)
                sucesso, motivo_v, snippet_v = self._verificar_sucesso_juntada(resp_post)
            
            if sucesso:
                record.status = 'juntado'
                record.save()
                self._log(record, 'resposta',
                    f"Nao foi possivel enviar o oficio por e-mail ({motivo}). "
                    f"Foi juntada no processo uma declaracao de impossibilidade de cumprimento.",
                    {'etapa': 'resposta_impossibilidade', 'observacao': observacao}
                )
                return True

        except Exception as e:
            self._log(record, 'erro_juntada',
                f"Erro na juntada de impossibilidade: {str(e)[:100]}",
                {'etapa': 'resposta_impossibilidade'}
            )

        return False

    def _gerar_texto_impossibilidade(self, record: OficioRecord, motivo: str = "") -> str:
        """Gera texto humanizado de impossibilidade para a juntada."""
        motivo_final = motivo or "e-mail de destinatario ausente ou invalido"
        texto = (
            f"Impossibilidade de cumprimento do Oficio n {record.numero_oficio}, "
            f"processo {record.numero_processo_cnj or record.processo}. Motivo: {motivo_final}. "
            f"Foi tentado o envio automatico em {datetime.now().strftime('%d/%m/%Y %H:%M')} "
            f"sem exito. Aguarda providencias do Cartorio para novo encaminhamento."
        )
        return texto

    # ------------------------------------------------------------------
    # FLUXO COMPLETO
    # ------------------------------------------------------------------
    def processar_oficio(self, record: OficioRecord) -> Dict:
        """
        Fluxo completo para um OficioRecord:
        - Envia e-mail
        - Se ok -> juntada de cumprimento
        - Se falha -> juntada de impossibilidade
        """
        resultado = {
            'enviado': False,
            'juntado': False,
            'erro': None,
        }

        if record.juntado:
            self._log(record, 'info',
                "Oficio ja consta como juntado. Nenhuma acao necessaria.",
                {'acao': 'skip'}
            )
            resultado['juntado'] = True
            return resultado

        # 1) Envia e-mail
        ok_envio, info = self.enviar_email(record)
        if ok_envio:
            resultado['enviado'] = True
            # 2) Juntada de cumprimento
            resultado['juntado'] = self.juntar_cumprimento(record)
        else:
            resultado['erro'] = info
            # 3) Juntada de impossibilidade (mesma funcao, mensagem diferente)
            try:
                motivo = self.humanizar_erro(info)
                obs = (
                    f"Impossibilidade de cumprimento do Oficio n {record.numero_oficio}, "
                    f"processo {record.numero_processo_cnj or record.processo}. "
                    f"Motivo: {motivo}. "
                    f"Foi tentado o envio automatico em "
                    f"{datetime.now().strftime('%d/%m/%Y %H:%M')} sem exito. "
                    f"Aguarda providencias do Cartorio para novo encaminhamento."
                )
                # Remove codDocVinculado para usar URL generica
                url_orig = record.url_recebimento
                if url_orig and 'codDocVinculado' in str(url_orig):
                    record.url_recebimento = str(url_orig).split('&codDocVinculado')[0]
                sucesso_j, _, _ = self._juntar_via_requests(record, '11383', observacao=obs)
                if url_orig:
                    record.url_recebimento = url_orig
                if sucesso_j:
                    record.status = 'juntado'
                    record.save(update_fields=['status', 'url_recebimento'])
                    resultado['juntado'] = True
            except Exception:
                pass

        return resultado

    def sincronizar_e_processar(self, quantidade: int = 3) -> Dict:
        """
        Busca oficios no Projudi (cookies salvos -> ultima pagina -> N ultimas paginas),
        importa para o banco e processa pendentes.
        Retorna resumo.
        """
        resumo = {'importados': 0, 'enviados': 0, 'juntados': 0, 'falhas': 0, 'logs': []}

        try:
            pendentes = self.buscar_oficios_pendentes(quantidade=quantidade)
        except Exception as e:
            resumo['logs'].append(f"Erro ao buscar oficios: {e}")
            traceback.print_exc()
            return resumo

        for dados in pendentes:
            oficio_data = self.extrair_oficio(dados)
            if not oficio_data:
                continue

            record = self.importar_oficio(oficio_data)
            resumo['importados'] += 1

            if record.pode_enviar:
                resultado = self.processar_oficio(record)
                if resultado['enviado']:
                    resumo['enviados'] += 1
                if resultado['juntado']:
                    resumo['juntados'] += 1
                if resultado['erro'] and not resultado['juntado']:
                    resumo['falhas'] += 1

        return resumo

    # ------------------------------------------------------------------
    # LOGS HUMANIZADOS
    # ------------------------------------------------------------------
    def _log(self, record: OficioRecord, tipo: str, mensagem: str, detalhes: Optional[Dict] = None):
        OficioLog.objects.create(
            oficio=record,
            tipo=tipo,
            mensagem=mensagem,
            detalhes=detalhes or {}
        )

    def logs_humanizados(self, record: OficioRecord) -> List[Dict]:
        """Retorna logs formatados para exibicao no template."""
        logs = []
        for log in record.logs.all():
            logs.append({
                'data': log.created_at.strftime('%d/%m/%Y %H:%M'),
                'tipo_label': log.get_tipo_display(),
                'tipo': log.tipo,
                'mensagem': log.mensagem,
                'detalhes': log.detalhes,
            })
        return logs

    def humanizar_erro(self, erro: str) -> str:
        """Traduz erros tecnicos para linguagem nao-tecnica."""
        erro = str(erro).lower()
        
        if 'jsessionid' in erro or 'sessao' in erro or 'expirada' in erro:
            return "A sessao do Projudi expirou. Abra o Firefox, faca login no Projudi e rode o script de captura de cookies novamente."

        if 'nenhum e-mail' in erro or 'email de destino' in erro or 'email nao encontrado' in erro:
            return "o oficio nao possui e-mail de destinatario."

        if 'smtp' in erro or 'email' in erro or 'gmail' in erro:
            return "Nao foi possivel enviar o e-mail. Verifique se a senha de app do Gmail esta configurada corretamente nas configuracoes."
        
        if 'timeout' in erro or 'connection' in erro or 'conexao' in erro:
            return "A conexao com o Projudi esta lenta ou indisponivel. Tente novamente em alguns instantes."
        
        if 'not found' in erro or '404' in erro:
            return "A pagina do oficio nao foi encontrada no Projudi. O oficio pode ter sido removido ou o numero do processo mudou."
        
        if 'juntada' in erro or 'cumprimento' in erro:
            return "Nao foi possivel registrar a juntada no Projudi. Verifique se voce tem permissao para movimentar este processo."
        
        if 'selenium' in erro or 'webdriver' in erro or 'gecko' in erro:
            return "O navegador automatizado nao conseguiu executar. O Firefox esta instalado? Tente sincronizar os cookies pelo Firefox aberto."
        
        if 'csv' in erro or 'protocolo' in erro:
            return "Erro ao registrar no protocolo CSV. O arquivo pode estar bloqueado por outro programa."
        
        if 'not null' in erro or 'tenant' in erro:
            return "Erro interno do sistema. Contate o administrador informando: 'erro de tenant'."
        
        # Erro generico mas amigavel
        return f"Ocorreu um problema inesperado: {str(erro)[:100]}. Se persistir, contate o suporte."

    def criar_log(self, record: OficioRecord, tipo: str, mensagem: str):
        """Cria um log humanizado para um oficio."""
        self._log(record, tipo, mensagem, {})

    def enviar_oficio(self, record: OficioRecord) -> Dict:
        """
        Envia oficio por e-mail.
        Retorna {'enviado': bool, 'erro': str|None}
        """
        ok, msg = self.enviar_email(record)
        return {'enviado': ok, 'erro': None if ok else msg}

    def juntar_oficio(self, record: OficioRecord) -> Dict:
        """
        Junta oficio no Projudi.
        Retorna {'juntado': bool, 'erro': str|None}
        """
        ok = self.juntar_cumprimento(record)
        return {'juntado': ok, 'erro': None if ok else 'Falha na juntada'}

    def juntar_resposta(self, record: OficioRecord) -> Dict:
        """
        Registra acuse de recebimento da resposta no Projudi (cod 2011).
        Segue o mesmo padrao de _juntar_via_requests.
        Retorna {'juntado': bool, 'erro': str|None}
        """
        if record.status_retorno == 'sem_retorno':
            return {'juntado': False, 'erro': 'Oficio sem resposta registrada'}
        if record.status_retorno == 'processado':
            return {'juntado': False, 'erro': 'Resposta ja foi juntada anteriormente'}

        try:
            sucesso, motivo, snippet = self._juntar_resposta_via_requests(record)
            if sucesso:
                record.status_retorno = 'processado'
                record.status = 'juntado'
                record.save(update_fields=['status_retorno', 'status'])
                self._log(record, 'resposta',
                    f"Resposta juntada no Projudi (Cumprimento de Oficio - 11383). {motivo}",
                    {'etapa': 'acuse', 'motivo_sucesso': motivo}
                )
                return {'juntado': True, 'erro': None}
            else:
                self._log(record, 'erro_juntada',
                    f"Juntada de resposta recusada pelo Projudi: {motivo}",
                    {'etapa': 'acuse', 'motivo_falha': motivo, 'snippet': snippet[:300]}
                )
                return {'juntado': False, 'erro': motivo}

        except Exception as e:
            self._log(record, 'erro_juntada',
                f"Erro tecnico ao juntar resposta: {str(e)[:100]}",
                {'etapa': 'acuse', 'erro': str(e)}
            )
            return {'juntado': False, 'erro': str(e)[:100]}

    def _juntar_resposta_via_requests(self, record: OficioRecord) -> Tuple[bool, str, str]:
        from bs4 import BeautifulSoup
        import time

        result = self.projudi_service._get_session_from_cookies()
        if result is None:
            raise Exception("Sessao nao disponivel")
        session, _ = result

        resp = session.get(record.url_recebimento, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")
        if 'login' in resp.url.lower():
            raise Exception("Sessao expirada - redirecionado para login")

        soup = BeautifulSoup(resp.text, 'html.parser')
        form = soup.find('form')
        if not form:
            raise Exception("Formulario nao encontrado")

        action = form.get('action', '')
        if action.startswith('/'):
            post_url = f"https://projudi.tjba.jus.br{action}"
        elif action.startswith('http'):
            post_url = action
        else:
            post_url = record.url_recebimento

        payload = {}
        for inp in form.find_all('input'):
            typ = inp.get('type', '')
            name = inp.get('name')
            if not name:
                continue
            if typ == 'checkbox':
                if inp.get('checked') is not None and name != 'codParteTransPenal':
                    payload[name] = inp.get('value', '')
            elif typ == 'radio':
                if inp.get('checked') is not None:
                    payload[name] = inp.get('value', '')
            elif typ in ('hidden', 'text', 'email', 'tel', 'number', 'date', ''):
                val = inp.get('value', '')
                if val or typ == 'hidden':
                    payload[name] = val
        for sel in form.find_all('select'):
            name = sel.get('name')
            if not name:
                continue
            selected = sel.find('option', selected=True)
            val = selected.get('value', '') if selected else ''
            if val and val not in ('-1', '0'):
                payload[name] = val
            elif name in ('acaoCodTipoLocalizador',):
                payload[name] = val
        for ta in form.find_all('textarea'):
            name = ta.get('name')
            if name:
                payload[name] = ta.get_text()

        payload['Concluir.x'] = '10'
        payload['Concluir.y'] = '10'
        payload['seqCategoriaMovimentacao'] = '11383'
        payload['descCategoriaMovimentacao'] = 'Cumprimento de Oficio'

        data_fmt = record.data_retorno or timezone.now()
        remetente = record.remetente_retorno or 'Remetente desconhecido'
        proc_cnj = record.numero_processo_cnj or record.processo

        # Corrige encoding latin-1 corrompido (ex: "2Âª" → "2ª", "NÂº" → "Nº")
        def _corrigir_latin(texto):
            try:
                return texto.encode('latin-1').decode('utf-8')
            except Exception:
                return texto

        remetente = _corrigir_latin(remetente)
        proc_cnj = _corrigir_latin(proc_cnj)

        # Extrai apenas o texto util da resposta (remove cabecalho de email)
        conteudo_raw = (record.conteudo_retorno or '').strip()
        conteudo_raw = _corrigir_latin(conteudo_raw)
        # Remove o prefixo "Assunto:..." que foi adicionado pelo receber_respostas
        resposta_util = re.sub(r'^Assunto:.*?\n\n', '', conteudo_raw, flags=re.DOTALL).strip()
        # Se ainda estiver vazio, usa o conteudo original truncado
        if not resposta_util:
            resposta_util = conteudo_raw[:100]

        # Formata observacao no padrao solicitado
        observacao = (
            f"RECEBIDO O OFICIO REF 2ª VSJ - {record.numero_oficio} - "
            f"Proc nº {proc_cnj} "
            f"por {remetente} "
            f"em {data_fmt.strftime('%d/%m/%Y')} as {data_fmt.strftime('%H:%M')} hs; "
            f"Resposta {resposta_util[:150]}"
        )
        payload['observacao'] = observacao
        payload['observacaoDiligencia'] = ''

        campos_indesejados = [
            'codDelegacia', 'codPrazoEnviaDelegacia',
            'enviaDelegacia', 'enviaMP', 'enviaTurmaRecursal',
            'enviaCartorioExtrajudicial', 'arquivar',
            'psicossocial', 'contador',
        ]
        for campo in campos_indesejados:
            payload.pop(campo, None)

        if isinstance(payload.get('codTipoLocalizador'), list):
            payload['codTipoLocalizador'] = payload['codTipoLocalizador'][-1]

        time.sleep(1)
        multipart_data = {k: (None, str(v).encode('latin-1', errors='replace')) for k, v in payload.items()}
        resp_post = session.post(post_url, files=multipart_data, timeout=15)

        sucesso, motivo, snippet = self._verificar_sucesso_juntada(resp_post)
        if not sucesso and '11383' in payload.get('seqCategoriaMovimentacao', ''):
            payload['seqCategoriaMovimentacao'] = '581'
            payload['descCategoriaMovimentacao'] = 'TD - Tipo Documental'
            multipart_data = {k: (None, str(v).encode('latin-1', errors='replace')) for k, v in payload.items()}
            time.sleep(1)
            resp_post = session.post(post_url, files=multipart_data, timeout=15)
            sucesso, motivo, snippet = self._verificar_sucesso_juntada(resp_post)

        return sucesso, motivo, snippet

    # ------------------------------------------------------------------
    # BAIXA AUTOMATICA (MarcaRecebimento)
    # ------------------------------------------------------------------
    def realizar_baixa(self, record: OficioRecord) -> Tuple[bool, str]:
        """Acessa url_baixa, preenche dataLeitura com a data atual e Submete.

        Usada para dar baixa em oficios cujo email ja foi respondido
        (status_retorno='recebido') apos o periodo de carência configurado.

        Retorna (sucesso, mensagem).
        """
        if not record.url_baixa:
            msg = "URL de baixa nao disponivel para este oficio."
            self._log(record, 'erro_baixa', msg, {'etapa': 'validacao'})
            return False, msg

        from bs4 import BeautifulSoup
        import time
        from datetime import date

        # 1. Sessao
        result = self.projudi_service._get_session_from_cookies()
        if result is None:
            msg = "Sessao nao disponivel para realizar baixa."
            self._log(record, 'erro_baixa', msg, {'etapa': 'sessao'})
            return False, msg
        session, _ = result

        # 2. Acessa pagina de MarcaRecebimento
        resp = session.get(record.url_baixa, timeout=15)
        if resp.status_code != 200:
            msg = f"HTTP {resp.status_code} ao acessar url_baixa."
            self._log(record, 'erro_baixa', msg, {'etapa': 'http'})
            return False, msg
        if 'login' in resp.url.lower():
            msg = "Sessao expirada - redirecionado para login."
            self._log(record, 'erro_baixa', msg, {'etapa': 'sessao'})
            return False, msg

        # 3. Parse do formulario
        soup = BeautifulSoup(resp.text, 'html.parser')
        form = soup.find('form')
        if not form:
            msg = "Formulario nao encontrado na pagina de baixa."
            self._log(record, 'erro_baixa', msg, {'etapa': 'parse'})
            return False, msg

        action = form.get('action', '')
        if action.startswith('/'):
            post_url = f"https://projudi.tjba.jus.br{action}"
        elif action.startswith('http'):
            post_url = action
        else:
            post_url = record.url_baixa

        # 4. Monta payload com todos os campos do form
        payload = {}
        for inp in form.find_all('input'):
            typ = inp.get('type', '')
            name = inp.get('name')
            if not name:
                continue
            if typ == 'checkbox':
                if inp.get('checked') is not None:
                    payload[name] = inp.get('value', '')
            elif typ == 'radio':
                if inp.get('checked') is not None:
                    payload[name] = inp.get('value', '')
            elif typ in ('hidden', 'text', 'email', 'tel', 'number', 'date', ''):
                val = inp.get('value', '')
                if val or typ == 'hidden':
                    payload[name] = val

        for sel in form.find_all('select'):
            name = sel.get('name')
            if not name:
                continue
            selected = sel.find('option', selected=True)
            val = selected.get('value', '') if selected else ''
            if val and val not in ('-1', '0'):
                payload[name] = val

        for ta in form.find_all('textarea'):
            name = ta.get('name')
            if name:
                payload[name] = ta.get_text()

        # 5. Preenche dataLeitura com a data de hoje
        hoje = date.today().strftime('%d/%m/%Y %H:%M')
        payload['dataLeitura'] = hoje

        # 6. Botao Submeter (image submit)
        payload['submit.x'] = '10'
        payload['submit.y'] = '10'

        # 7. Remove campos problemáticos se existirem
        for campo in ['codDelegacia', 'codPrazoEnviaDelegacia',
                      'enviaDelegacia', 'enviaMP', 'enviaTurmaRecursal',
                      'enviaCartorioExtrajudicial', 'arquivar',
                      'psicossocial', 'contador']:
            payload.pop(campo, None)

        # 8. Envia
        time.sleep(1)
        multipart_data = {
            k: (None, str(v).encode('latin-1', errors='replace'))
            for k, v in payload.items()
        }
        resp_post = session.post(post_url, files=multipart_data, timeout=15)

        # 9. Verifica resultado
        if resp_post.status_code != 200:
            msg = f"HTTP {resp_post.status_code} ao submeter baixa."
            self._log(record, 'erro_baixa', msg, {'etapa': 'submeter'})
            return False, msg
        if 'login' in resp_post.url.lower():
            msg = "Sessao expirou durante a baixa."
            self._log(record, 'erro_baixa', msg, {'etapa': 'sessao'})
            return False, msg

        # Sucesso
        record.status_retorno = 'processado'
        record.save(update_fields=['status_retorno'])

        self._log(record, 'info',
            f"Baixa realizada em {hoje} via MarcaRecebimento.",
            {'etapa': 'baixa', 'url': record.url_baixa}
        )
        return True, f"Baixa realizada em {hoje}"

    def fechar(self):
        """Libera recursos Selenium."""
        if self._juntada:
            self._juntada.close()
