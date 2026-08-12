"""
Refatoração OO do enviar.ipynb

Estrutura:
- EmailSender: Envia emails
- ProjudiJuntada: Realiza juntadas no Projudi
- OficioProcessor: Processa ofícios (extrai dados, coordena envio+juntada)
- ProtocoloCSV: Gerencia o CSV de protocolo
"""

import smtplib
import re
import csv
import os
import time
import random
from datetime import datetime
from email.message import EmailMessage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import make_msgid
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from webdriver_manager.firefox import GeckoDriverManager


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class OficioData:
    """Dados extraídos de um ofício"""
    processo: str
    numero_oficio: str
    email_destino: str
    url_oficio: str
    url_processo: str
    url_recebimento: str
    url_baixa: str
    texto_html: str
    assunto: str = ''
    processo_cnj: str = ''  # <-- numero CNJ visivel no link
    
    def __post_init__(self):
        if not self.assunto:
            proc = self.processo_cnj or self.processo
            self.assunto = f"2ªVSJ - {self.numero_oficio} Referente ao Proc Nº: {proc}"


@dataclass
class EmailConfig:
    """Configuração de email"""
    smtp_server: str = 'smtp.gmail.com'
    smtp_port: int = 465
    remetente: str = ''
    senha_app: str = ''
    destino_padrao: str = 'pafonso-2vsj@tjba.jus.br'


@dataclass
class ProjudiConfig:
    """Configuração do Projudi"""
    link_base: str = 'https://projudi.tjba.jus.br/projudi/'
    codigo_juntada: str = '581'


# =============================================================================
# EMAIL SENDER
# =============================================================================

class EmailSender:
    """Envia emails com ofícios judiciais"""
    
    def __init__(self, config: EmailConfig):
        self.config = config
    
    def enviar_oficio(self, oficio: OficioData) -> Tuple[bool, str]:
        """
        Envia email com ofício
        
        Returns:
            (sucesso, msg_id ou erro)
        """
        msg = self._construir_mensagem(oficio)
        
        try:
            with smtplib.SMTP_SSL(self.config.smtp_server, self.config.smtp_port) as servidor:
                servidor.login(self.config.remetente, self.config.senha_app)
                servidor.send_message(msg)
            
            msg_id = msg['Message-ID'].strip('<>')
            return True, msg_id
            
        except Exception as e:
            return False, str(e)
    
    def _construir_mensagem(self, oficio: OficioData) -> MIMEMultipart:
        """Constrói mensagem de email com HTML e brasão"""

        from datetime import datetime
        logo_cid = make_msgid(domain="tjba.jus.br")[1:-1]
        msg_id = make_msgid()

        # Subject padronizado: "Oficio - nº XXX/2026 - SEC"
        assunto_oficio = oficio.numero_oficio.strip()
        if not assunto_oficio:
            assunto_oficio = oficio.assunto or "Oficio"
        subject = f"Oficio - n\xba {assunto_oficio}"

        # Corpo com protocolo
        agora = datetime.now()
        protocolo = agora.strftime("%d/%m/%Y as %H:%M")
        html = self._gerar_html(oficio.texto_html, logo_cid, protocolo, oficio.email_destino, oficio.url_oficio)
        
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = self.config.remetente
        msg["To"] = oficio.email_destino
        msg["Message-ID"] = msg_id
        msg.add_header('Return-Receipt-To', self.config.remetente)
        
        # HTML
        alt_part = MIMEMultipart("alternative")
        html_part = MIMEText(html, 'html', 'utf-8')
        alt_part.attach(html_part)
        msg.attach(alt_part)
        
        # Brasao (opcional - se nao existir, envia sem)
        brasao_path = os.path.join(os.path.dirname(__file__), "tjba.png")
        if not os.path.exists(brasao_path):
            # Tenta no diretorio raiz do projeto
            brasao_path = "tjba.png"
        
        if os.path.exists(brasao_path):
            try:
                with open(brasao_path, 'rb') as img_file:
                    img = MIMEImage(img_file.read(), _subtype="png")
                    img.add_header('Content-ID', f'<{logo_cid}>')
                    img.add_header('Content-Disposition', 'inline', filename="brasao_tjba.png")
                    msg.attach(img)
            except Exception:
                pass  # Se falhar, envia sem brasao
        
        return msg
    
    def _gerar_html(self, texto_oficio: str, logo_cid: str,
                    protocolo: str = '', email_destino: str = '',
                    url_oficio: str = '') -> str:
        """Gera HTML do email com protocolo e info de envio"""
        bloco_protocolo = ''
        if protocolo:
            bloco_protocolo = f"""
            <hr style="margin: 20px auto; width: 80%; border: none; border-top: 1px solid #ccc;">
            <div style="font-size: 11px; color: #666; text-align: center;">
                Protocolado em {protocolo}<br>
                E-mail: {email_destino}<br>
                Link: <a href="{url_oficio}" style="color: #2563eb;">{url_oficio}</a>
            </div>"""
        return f"""
        <html>
        <head></head>
        <body style="font-family: Arial, sans-serif; font-size: 14px;">
            <p>Prezado(a) Senhor(a),</p>
            <p>Este endereço de email é <b>apenas para fins de envio AUTOMÁTICO de Ofícios</b>. Encaminhamos o documento abaixo.</p>
            <p>Por favor, acuse o recebimento.
            <P>Caso seja necessário enviar um Ofício de resposta, envie-o para o email: <b>pafonso-2vsj@tjba.jus.br</b></p>
            <br>
            <p style="margin-bottom: 10px;">Atenciosamente,<br><br>
            2ª Vara do Sistema dos Juizados Especiais – TJBA</p>
            <br><br>
            <div style="text-align: center;" align="center">
                <img src="cid:{logo_cid}" style="height:80px;" alt="Brasão TJBA">
            </div>
            <div style="margin-top: 2px; text-align: center;">
                2ª Vara dos Juizados Especiais de Paulo Afonso – BA<br>
                Rua das Caraibeiras, 420, Quadra 04 1º Andar, General Dutra - Fórum de Paulo Afonso <br>
                pafonso-2vsj@tjba.jus.br // Tel.: (75) 32818 - 8372
            </div> <br>
            <hr style="margin: 20px auto; width: 60%; border: none; border-top: 1px solid #ccc;">
            <div style="text-align: justify; margin: 0 auto; width: 80%; max-width: 600px;">
            {texto_oficio}
            </div>
            {bloco_protocolo}
        </body>
        </html>
        """


# =============================================================================
# PROJUDI JUNTADA
# =============================================================================

class ProjudiJuntada:
    """Realiza juntadas no Projudi via Selenium"""
    
    def __init__(self, config: ProjudiConfig, cookies: Dict, driver=None):
        self.config = config
        self.cookies = cookies
        self._driver = driver
    
    @property
    def driver(self):
        if self._driver is None:
            self._driver = self._criar_driver()
        return self._driver
    
    def _criar_driver(self) -> webdriver.Firefox:
        """Cria driver Selenium com cookies injetados"""
        profile = FirefoxProfile()
        profile.set_preference("general.useragent.override",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0"
        )
        profile.set_preference("intl.accept_languages", "pt-BR,pt;q=0.9,en;q=0.8")
        
        options = Options()
        options.profile = profile
        
        # Firefox ESR no WSL
        firefox_binary = '/opt/firefox-esr/firefox'
        if os.path.exists(firefox_binary):
            options.binary_location = firefox_binary
        
        # Modo headless para WSL (sem interface grafica)
        options.add_argument('--headless')
        
        service = Service(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=options)
        driver.set_window_size(1280, 800)
        
        # Injeta cookies - mesma sessao do usuario
        driver.get(self.config.link_base)
        for name, value in self.cookies.items():
            driver.add_cookie({
                'name': name,
                'value': value,
                'path': '/',
                'domain': 'projudi.tjba.jus.br',
                'secure': True
            })
        
        return driver
    
    def realizar_juntada(
        self, 
        url_recebimento: str,
        numero_oficio: str,
        data_envio: str,
        hora_envio: str,
        destinatario: str,
        url_oficio: str
    ) -> bool:
        """
        Realiza juntada de recebimento no Projudi
        
        Returns:
            True se sucesso, False se falha
        """
        try:
            driver = self.driver
            wait = WebDriverWait(driver, 20)
            
            # 1. Navega para página de recebimento
            driver.get(url_recebimento)
            self._human_delay(2, 4)
            
            # 2. Scroll
            driver.execute_script("window.scrollBy(0, 567);")
            
            # 3. Preenche código da movimentação
            codigo_field = wait.until(
                EC.presence_of_element_located((By.ID, "seqCategoriaMovimentacao"))
            )
            codigo_field.clear()
            self._digitar_como_humano(codigo_field, self.config.codigo_juntada)
            self._human_delay(1, 2)
            
            # 4. Clica buscar
            btn_busca = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "btnBuscaMovimentacao"))
            )
            btn_busca.click()
            self._human_delay(2, 3)
            
            # 5. Preenche observação
            obs_field = wait.until(
                EC.presence_of_element_located((By.ID, "observacao"))
            )
            obs_field.clear()
            
            observacao = (
                f"Email enviado por {self.config.remetente if hasattr(self.config, 'remetente') else 'sistema'} - "
                f"{numero_oficio} em {data_envio} às {hora_envio}, "
                f"para: {destinatario}, link: {url_oficio}"
            )
            self._digitar_como_humano(obs_field, observacao)
            
            # 6. Scroll e concluir
            driver.execute_script("window.scrollBy(0, 567);")
            self._human_delay(1, 2)
            
            btn_concluir = wait.until(
                EC.element_to_be_clickable((By.ID, "Concluir"))
            )
            btn_concluir.click()
            self._human_delay(2, 3)
            
            # 7. Aceita alerta
            alert = WebDriverWait(driver, 10).until(EC.alert_is_present())
            print(f"Alerta: {alert.text}")
            alert.accept()
            self._human_delay(2, 3)
            
            print("✅ Juntada realizada com sucesso!")
            return True
            
        except Exception as e:
            print(f"❌ Erro na juntada: {e}")
            return False
    
    def _digitar_como_humano(self, element, text: str):
        """Digita como um humano"""
        for letra in text:
            element.send_keys(letra)
            time.sleep(random.randint(1, 6) / 25)
    
    def _human_delay(self, min_sec: float = 1, max_sec: float = 3):
        """Delay aleatório"""
        time.sleep(random.uniform(min_sec, max_sec))
    
    def close(self):
        """Fecha o driver"""
        if self._driver:
            self._driver.quit()
            self._driver = None


# =============================================================================
# PROTOCOLO CSV
# =============================================================================

class ProtocoloCSV:
    """Gerencia o CSV de protocolo de emails"""
    
    CAMPOS = [
        'processo', 'num_oficio', 'email_destino', 'status',
        'data_envio', 'hora_envio', 'registrar_envio', 'resposta', 'msg_id',
        'url_oficio', 'url_processo', 'url_recebimento', 'url_baixa', 'assunto',
    ]
    
    def __init__(self, path: str = 'protocolo_email_projudi.csv'):
        self.path = path
        self._garantir_arquivo()
    
    def _garantir_arquivo(self):
        """Cria arquivo se não existir"""
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.CAMPOS, delimiter=';')
                writer.writeheader()
    
    def carregar(self) -> List[Dict]:
        """Carrega dados do CSV"""
        with open(self.path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f, delimiter=';')
            return list(reader)
    
    def salvar(self, dados: List[Dict]):
        """Salva dados no CSV"""
        with open(self.path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.CAMPOS, delimiter=';')
            writer.writeheader()
            writer.writerows(dados)
    
    def buscar_registro(self, processo: str, numero_oficio: str) -> Optional[Dict]:
        """Busca registro por processo e ofício"""
        dados = self.carregar()
        for linha in dados:
            if (linha.get('processo', '').strip() == processo and 
                linha.get('num_oficio', '').strip() == numero_oficio):
                return linha
        return None
    
    def ja_enviado_e_juntado(self, processo: str, numero_oficio: str) -> bool:
        """Verifica se já foi enviado e juntado"""
        registro = self.buscar_registro(processo, numero_oficio)
        if not registro:
            return False
        
        status = registro.get('status', '').strip().lower()
        juntado = registro.get('registrar_envio', '').strip().lower() in ('juntado', 'cumprido', 'baixado')
        
        return status == 'enviado' and juntado
    
    def registrar_envio(
        self,
        oficio: OficioData,
        msg_id: str,
        data_envio: str,
        hora_envio: str
    ):
        """Registra envio no CSV"""
        dados = self.carregar()
        
        nova_linha = {
            'processo': oficio.processo,
            'num_oficio': oficio.numero_oficio,
            'email_destino': oficio.email_destino,
            'status': 'Enviado',
            'data_envio': data_envio,
            'hora_envio': hora_envio,
            'registrar_envio': '',
            'resposta': '',
            'msg_id': msg_id,
            'url_oficio': oficio.url_oficio,
            'url_processo': oficio.url_processo,
            'url_recebimento': oficio.url_recebimento,
            'url_baixa': oficio.url_baixa,
            'assunto': oficio.assunto,
        }
        
        # Evita duplicados
        if not any(
            l['processo'].strip() == oficio.processo and 
            l['num_oficio'].strip() == oficio.numero_oficio 
            for l in dados
        ):
            dados.append(nova_linha)
            self.salvar(dados)
            print(f"[✓] Registro adicionado para {oficio.processo} - {oficio.numero_oficio}")
    
    def atualizar_juntada(self, processo: str, numero_oficio: str):
        """Atualiza status de juntada"""
        dados = self.carregar()
        
        for linha in dados:
            if (linha.get('processo', '').strip() == processo and 
                linha.get('num_oficio', '').strip() == numero_oficio):
                linha['registrar_envio'] = 'juntado'
                break
        
        self.salvar(dados)
        print(f"[✓] Juntada registrada para {processo} - {numero_oficio}")


# =============================================================================
# OFICIO PROCESSOR (ORQUESTRADOR)
# =============================================================================

class OficioProcessor:
    """Processa ofícios: extrai dados, envia email, realiza juntada"""
    
    def __init__(
        self,
        email_sender: EmailSender,
        juntada: ProjudiJuntada,
        protocolo: ProtocoloCSV
    ):
        self.email_sender = email_sender
        self.juntada = juntada
        self.protocolo = protocolo
    
    def processar(self, oficio: OficioData) -> Dict:
        """
        Processa ofício completo
        
        Returns:
            Dict com status do processamento
        """
        resultado = {
            'processo': oficio.processo,
            'numero_oficio': oficio.numero_oficio,
            'email_enviado': False,
            'juntada_realizada': False,
            'erro': None
        }
        
        # Verifica se já foi processado
        if self.protocolo.ja_enviado_e_juntado(oficio.processo, oficio.numero_oficio):
            print(f"[INFO] {oficio.numero_oficio} já enviado e juntado. Nada a fazer.")
            resultado['erro'] = 'já_processado'
            return resultado
        
        # Verifica se só falta juntada
        registro = self.protocolo.buscar_registro(oficio.processo, oficio.numero_oficio)
        if registro and registro.get('status', '').lower() == 'enviado':
            print(f"[INFO] {oficio.numero_oficio} já enviado. Realizando apenas juntada.")
            resultado['juntada_realizada'] = self._realizar_juntada(oficio, registro)
            return resultado
        
        # Envia email
        print(f"[INFO] Enviando email para {oficio.processo} - {oficio.numero_oficio}")
        sucesso, msg_id = self.email_sender.enviar_oficio(oficio)
        
        if not sucesso:
            resultado['erro'] = f'Erro ao enviar email: {msg_id}'
            return resultado
        
        resultado['email_enviado'] = True
        
        # Registra envio
        data_envio = datetime.now().strftime('%d/%m/%Y')
        hora_envio = datetime.now().strftime('%H:%M:%S')
        self.protocolo.registrar_envio(oficio, msg_id, data_envio, hora_envio)
        
        # Realiza juntada
        resultado['juntada_realizada'] = self._realizar_juntada(
            oficio, 
            {'data_envio': data_envio, 'hora_envio': hora_envio}
        )
        
        return resultado
    
    def _realizar_juntada(self, oficio: OficioData, registro: Dict) -> bool:
        """Realiza juntada no Projudi"""
        sucesso = self.juntada.realizar_juntada(
            url_recebimento=oficio.url_recebimento,
            numero_oficio=oficio.numero_oficio,
            data_envio=registro.get('data_envio', datetime.now().strftime('%d/%m/%Y')),
            hora_envio=registro.get('hora_envio', datetime.now().strftime('%H:%M:%S')),
            destinatario=oficio.email_destino,
            url_oficio=oficio.url_oficio
        )
        
        if sucesso:
            self.protocolo.atualizar_juntada(oficio.processo, oficio.numero_oficio)
        
        return sucesso


# =============================================================================
# OFICIO EXTRACTOR
# =============================================================================

class OficioExtractor:
    """Extrai dados de ofícios do HTML do Projudi"""
    
    PADRAO_NUMERO = re.compile(
        r"Of[ií]cio\s*(n[ºo°.:]*)?\s*[:\-]?\s*([\d]{1,4}/[\d]{4}(?:\s*-\s*[A-Z]+)?)",
        re.IGNORECASE
    )
    
    PADRAO_EMAIL = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    
    EMAILS_INTERNOS = re.compile(r"@tjba|@tjbacote|pafonso-2vsj@tjba\.jus\.br", re.IGNORECASE)
    
    def extrair_de_html(self, html: str, processo: str, urls: Dict, processo_cnj: str = '') -> Optional[OficioData]:
        """
        Extrai dados de ofício do HTML
        
        Args:
            html: HTML da página do ofício
            processo: Número do processo (interno Projudi)
            urls: Dict com url_oficio, url_processo, url_recebimento, url_baixa
            processo_cnj: Número CNJ do processo (visível no link)
        
        Returns:
            OficioData ou None se não conseguir extrair
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Busca div do ofício
        div_oficio = soup.find('div', attrs={
            "style": re.compile(r"width:\s*650px.*font-family:\s*Tahoma", re.IGNORECASE)
        })
        
        if not div_oficio:
            div_oficio = soup.find('div', style=lambda s: s and 'width: 650px' in s)
        
        if not div_oficio:
            print(f"❌ Ofício do processo {processo} não encontrado.")
            return None
        
        # Extrai texto
        texto = div_oficio.get_text(separator='\n', strip=True)
        texto_html = str(div_oficio)
        
        # Extrai número do ofício
        match = self.PADRAO_NUMERO.search(texto)
        numero_oficio = match.group(2).strip() if match else ""
        
        if not numero_oficio:
            print(f"❌ Número do ofício não encontrado para {processo}")
            return None
        
        # Extrai email destinatário
        emails = self.PADRAO_EMAIL.findall(texto)
        emails_validos = [
            e for e in emails 
            if not self.EMAILS_INTERNOS.search(e)
        ]
        email_destino = emails_validos[0] if emails_validos else ""
        
        if not email_destino:
            print(f"⚠️ Email destinatário não encontrado para {processo}")
        
        return OficioData(
            processo=processo,
            numero_oficio=numero_oficio,
            email_destino=email_destino,
            url_oficio=urls.get('url_oficio', ''),
            url_processo=urls.get('url_processo', ''),
            url_recebimento=urls.get('url_recebimento', ''),
            url_baixa=urls.get('url_baixa', ''),
            texto_html=texto_html,
            processo_cnj=processo_cnj
        )


# =============================================================================
# EXEMPLO DE USO
# =============================================================================

def main():
    """Exemplo de uso completo"""
    
    # Configurações
    email_config = EmailConfig(
        remetente='pafonso.2vsj@gmail.com',
        senha_app='ouysuorpvqprfqig'  # Senha de app do Gmail
    )
    
    projudi_config = ProjudiConfig()
    
    # Inicializa componentes
    email_sender = EmailSender(email_config)
    
    # Precisa dos cookies do ProjudiBot
    # from projudi_bot import ProjudiBot
    # bot = ProjudiBot()
    # bot.executar()
    # cookies = bot.exportar_cookies()
    
    # juntada = ProjudiJuntada(projudi_config, cookies)
    # protocolo = ProtocoloCSV()
    
    # extractor = OficioExtractor()
    # processor = OficioProcessor(email_sender, juntada, protocolo)
    
    print("✅ Classes inicializadas com sucesso!")
    print("\nPara usar:")
    print("""
    # 1. Inicializar ProjudiBot para obter cookies
    from projudi_bot import ProjudiBot
    bot = ProjudiBot()
    bot.executar()
    cookies = bot.exportar_cookies()
    
    # 2. Criar componentes
    email_config = EmailConfig(remetente='...', senha_app='...')
    email_sender = EmailSender(email_config)
    juntada = ProjudiJuntada(ProjudiConfig(), cookies)
    protocolo = ProtocoloCSV()
    
    # 3. Processar ofício
    extractor = OficioExtractor()
    processor = OficioProcessor(email_sender, juntada, protocolo)
    
    oficio = extractor.extrair_de_html(html, processo, urls)
    resultado = processor.processar(oficio)
    """)


if __name__ == "__main__":
    main()
