"""
receber_respostas.py
====================
Script responsável por:
  1. Ler a caixa de entrada do Gmail (IMAP)
  2. Para cada e-mail novo:
     a) Encaminhar para o endereço interno (pafonso-2vsj@tjba.jus.br) se tiver PDF
        → Encaminha UMA ÚNICA VEZ por e-mail (controle via msg_id no CSV)
     b) Registrar a resposta recebida no Projudi via Selenium (juntada de acuse)
  3. Atualizar o CSV de protocolo

Uso:
    python receber_respostas.py

Correção do bug de encaminhamentos repetidos:
  - Antes de encaminhar, o script verifica se o msg_id já está registrado no CSV
  - O msg_id é salvo imediatamente após o encaminhamento
  - Na próxima execução, esse e-mail é ignorado

Boas práticas aplicadas:
  - Constantes centralizadas no topo do arquivo
  - Funções com responsabilidade única (SRP)
  - Controle de duplicidade por msg_id (não por assunto, que pode mudar)
  - Type hints e docstrings em todas as funções públicas
  - Nenhuma lógica duplicada (DRY)
"""

# ── Biblioteca padrão ────────────────────────────────────────────────────────
import csv
import os
import re
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage

# ── Dependências externas ────────────────────────────────────────────────────
import pandas as pd
from bs4 import BeautifulSoup
from imap_tools import MailBox, A
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES  ← edite apenas aqui
# ════════════════════════════════════════════════════════════════════════════
CONFIG = {
    # Credenciais Gmail
    "imap_server":   "imap.gmail.com",
    "smtp_server":   "smtp.gmail.com",
    "smtp_port":      587,
    "usuario":        os.getenv("GMAIL_USER",     "pafonso.2vsj@gmail.com"),
    "senha_app":      os.getenv("GMAIL_APP_PASS", "ouysuorpvqprfqig"),

    # Destino interno para encaminhamento de PDFs recebidos
    "destinatario_interno": "pafonso-2vsj@tjba.jus.br",

    # Quantos e-mails buscar por execução
    "limite_emails": 100,

    # Projudi
    "link_base":  "https://projudi.tjba.jus.br/projudi/",
    "cookies": {
        'ADC_CONN_539B3595F4E':	"574CAA1662357EBBF5F94ED94FF66FE08C10454FD7424D566BCB2DD33BADE9781AE5CBFD4E50793B",
        'ADC_REQ_2E94AF76E7':	"17EB80EF2601FF13E17C4D41F54A5E701355460BBCC88D1E3722D8C48FB521953AE37A4688C180D2",
        'ADRUM':	"s~1773170981656&r~aHR0cHMlM0ElMkYlMkZwcm9qdWRpLnRqYmEuanVzLmJyJTJGcHJvanVkaSUyRg==",
        'JSESSIONID':	"B35B5F86AE9CED4135E5A05BE4E0EA6D.tomcat09-03",
    },

    # CSV de protocolo
    "path_csv": "protocolo_email_projudi.csv",

    # PDFs que devem ser ignorados no encaminhamento (já processados manualmente)
    "pdfs_ignorados": {
        "3.Sgt PM Kelson e Sgt PM Marilson 204.2025.sec_0001.pdf",
        "Oficio_00126551581.pdf",
        "Extrato_00122965493_2VSJ_SGT_SANTOS.pdf",
        "ADILSON MOREIRA_0001.pdf",
        "Oficio_00124493202.pdf",
        "Requerimento_0087935422_EMAIL_1.pdf",
        "Oficio_00122965336.pdf",
    },
}

CAMPOS_CSV = [
    "processo", "num_oficio", "email_destino", "status",
    "data_envio", "hora_envio", "registrar_envio", "resposta", "msg_id",
    "url_oficio", "url_processo", "url_recebimento", "url_baixa", "assunto",
]

# Status que indicam que o registro já foi finalizado (não precisa mais de ação)
STATUS_FINAIS = {"recebido", "cumprido", "informado", "devolvido", "juntado"}


# ════════════════════════════════════════════════════════════════════════════
# CSV
# ════════════════════════════════════════════════════════════════════════════

def carregar_msg_ids_encaminhados(path_csv: str) -> set:
    """
    Retorna o conjunto de msg_ids de e-mails que já foram encaminhados.
    Essa é a chave para evitar encaminhamentos duplicados.
    """
    try:
        df = pd.read_csv(path_csv, sep=";", dtype=str)
        if "msg_id" in df.columns:
            return set(df["msg_id"].dropna().str.strip())
    except FileNotFoundError:
        pass
    return set()


def carregar_mapa_assuntos(path_csv: str) -> dict:
    """
    Lê o CSV e retorna um dicionário mapeando assunto normalizado → linha do CSV.
    Usado para cruzar respostas recebidas com ofícios enviados.
    """
    mapa = {}
    try:
        with open(path_csv, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                assunto = row.get("assunto", "").strip()
                if assunto:
                    mapa[_normalizar_assunto(assunto)] = row
    except FileNotFoundError:
        pass
    return mapa


def carregar_dados_csv(path_csv: str) -> list[dict]:
    """Carrega todos os registros do CSV como lista de dicionários."""
    dados = []
    try:
        with open(path_csv, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if str(row.get("processo", "")).strip().lower() == "processo":
                    continue
                for campo in CAMPOS_CSV:
                    row[campo] = str(row.get(campo) or "").strip()
                dados.append(row)
    except FileNotFoundError:
        pass
    return dados


def salvar_dados_csv(path_csv: str, dados: list[dict]) -> None:
    """Sobrescreve o CSV com a lista de dicionários fornecida."""
    with open(path_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV, delimiter=";")
        writer.writeheader()
        writer.writerows(dados)
    print(f"[✓] CSV salvo com {len(dados)} registros.")


def registrar_encaminhamento_no_csv(
    path_csv: str,
    dados: list[dict],
    msg_id: str,
    remetente: str,
    assunto: str,
    nome_pdf: str,
) -> None:
    """
    Adiciona uma linha de encaminhamento ao CSV e salva imediatamente.
    Isso garante que na próxima execução o msg_id seja reconhecido.

    IMPORTANTE: o CSV é salvo aqui (não apenas em memória) para evitar
    que uma interrupção do programa cause encaminhamentos duplicados na
    próxima execução.
    """
    agora = datetime.now()
    nova_linha = {
        "processo":        "",
        "num_oficio":      nome_pdf,
        "email_destino":   remetente,
        "status":          "encaminhado",
        "data_envio":      agora.strftime("%d/%m/%Y"),
        "hora_envio":      agora.strftime("%H:%M:%S"),
        "registrar_envio": "encaminhado",
        "resposta":        "",
        "msg_id":          msg_id,
        "url_oficio":      "",
        "url_processo":    "",
        "url_recebimento": "",
        "url_baixa":       "",
        "assunto":         assunto,
    }
    dados.append(nova_linha)
    salvar_dados_csv(path_csv, dados)
    print(f"  [✓] msg_id {msg_id[:20]}... salvo no CSV.")


# ════════════════════════════════════════════════════════════════════════════
# HELPERS DE TEXTO
# ════════════════════════════════════════════════════════════════════════════

def _normalizar_assunto(assunto: str) -> str:
    """Remove prefixos Re/Fwd e normaliza para minúsculas."""
    assunto = assunto.lower()
    assunto = re.sub(r"^(re|res|enc|fwd|fw)\s*:\s*", "", assunto)
    return assunto.strip()


def _limpar_cid(texto: str) -> str:
    """Remove referências CID inline, ex: [cid:image001.png@...]."""
    return re.sub(r"\[cid:[^\]]+\]", "", texto)


# ════════════════════════════════════════════════════════════════════════════
# VERIFICAÇÕES DE ANEXO
# ════════════════════════════════════════════════════════════════════════════

def tem_pdf_novo(msg, msg_ids_ja_processados: set) -> bool:
    """
    Retorna True se o e-mail contiver pelo menos um PDF que:
      - Não está na lista de PDFs ignorados (processados manualmente)
      - O msg_id do e-mail ainda não foi registrado no CSV

    A verificação por msg_id é feita ANTES de chamar esta função,
    mas mantemos a checagem de PDFs ignorados aqui como segunda camada.
    """
    for anexo in msg.attachments:
        nome = (anexo.filename or "").strip()
        if nome.lower().endswith(".pdf") and nome not in CONFIG["pdfs_ignorados"]:
            return True
    return False


def tem_anexo_relevante(msg) -> bool:
    """Retorna True se houver qualquer PDF, DOC ou DOCX no e-mail."""
    extensoes = {".pdf", ".doc", ".docx"}
    return any(
        (anexo.filename or "").lower().endswith(tuple(extensoes))
        for anexo in msg.attachments
    )


# ════════════════════════════════════════════════════════════════════════════
# ENCAMINHAMENTO
# ════════════════════════════════════════════════════════════════════════════

def encaminhar_email_com_pdfs(msg) -> bool:
    """
    Encaminha o e-mail recebido (com PDFs) para o endereço interno do cartório.
    Inclui o corpo original e todos os PDFs como anexos.

    Returns:
        True se enviado com sucesso, False caso contrário.
    """
    usuario    = CONFIG["usuario"]
    destinatario = CONFIG["destinatario_interno"]

    email = EmailMessage()
    email["Subject"] = f"Enc: {msg.subject or '(sem assunto)'}"
    email["From"]    = usuario
    email["To"]      = destinatario

    corpo_original = msg.text or (
        BeautifulSoup(msg.html, "html.parser").get_text() if msg.html else "(sem conteúdo)"
    )
    data_formatada = msg.date.strftime("%d/%m/%Y %H:%M") if msg.date else "data desconhecida"
    pdfs = [a.filename for a in msg.attachments if (a.filename or "").lower().endswith(".pdf")]

    corpo = (
        f"Encaminhado automaticamente.\n\n"
        f"{'─' * 40}\n"
        f"📨 Remetente original: {msg.from_}\n"
        f"📅 Data: {data_formatada}\n"
        f"📄 Assunto original: {msg.subject}\n"
        f"📎 PDFs: {pdfs}\n"
        f"{'─' * 40}\n\n"
        f"{corpo_original}"
    )
    email.set_content(corpo)

    pdfs_anexados = 0
    for anexo in msg.attachments:
        nome = anexo.filename or ""
        if nome.lower().endswith(".pdf"):
            email.add_attachment(
                anexo.payload,
                maintype="application",
                subtype="pdf",
                filename=nome,
            )
            pdfs_anexados += 1

    if pdfs_anexados == 0:
        print(f"  ⚠️  Nenhum PDF encontrado em: {msg.subject}")
        return False

    try:
        with smtplib.SMTP(CONFIG["smtp_server"], CONFIG["smtp_port"]) as smtp:
            smtp.starttls()
            smtp.login(usuario, CONFIG["senha_app"])
            smtp.send_message(email)
        print(f"  ✅ Encaminhado para {destinatario}: '{msg.subject}'")
        return True
    except Exception as exc:
        print(f"  ❌ Erro ao encaminhar '{msg.subject}': {exc}")
        return False


# ════════════════════════════════════════════════════════════════════════════
# SELENIUM – Juntada de acuse no Projudi
# ════════════════════════════════════════════════════════════════════════════

def _criar_driver_firefox() -> webdriver.Firefox:
    """Instancia o Firefox com perfil configurado."""
    profile = FirefoxProfile()
    profile.set_preference(
        "general.useragent.override",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0",
    )
    profile.set_preference("intl.accept_languages", "pt-BR,pt;q=0.9,en;q=0.8")
    options = Options()
    options.profile = profile
    driver = webdriver.Firefox(
        service=Service(GeckoDriverManager().install()),
        options=options,
    )
    driver.set_window_size(1280, 800)
    return driver


def _digitar_devagar(texto: str, elemento) -> None:
    """Simula digitação humana."""
    import random
    for letra in texto:
        elemento.send_keys(letra)
        time.sleep(random.randint(1, 6) / 25)


def registrar_acuse_projudi(
    url_recebimento: str,
    assunto: str,
    remetente: str,
    data_resposta: str,
    hora_resposta: str,
) -> bool:
    """
    Registra o acuse de recebimento de uma resposta diretamente no Projudi.

    Args:
        url_recebimento: URL do formulário de movimentação.
        assunto:         Assunto do ofício (para compor a observação).
        remetente:       E-mail de quem respondeu.
        data_resposta:   Data da resposta (formato dd/mm/yyyy).
        hora_resposta:   Hora da resposta (formato HH:MM:SS).

    Returns:
        True se registrado com sucesso.
    """
    link_base = CONFIG["link_base"]
    cookies   = CONFIG["cookies"]

    driver = _criar_driver_firefox()

    # Injeta cookies
    from urllib.parse import urlparse
    driver.get(link_base)
    time.sleep(2)
    parsed = urlparse(link_base)
    for name, value in cookies.items():
        driver.add_cookie({
            "name": name, "value": value,
            "path": "/", "domain": parsed.hostname, "secure": True,
        })

    wait = WebDriverWait(driver, 20)

    try:
        driver.get(url_recebimento)
        driver.execute_script("window.scrollBy(0, 567);")

        campo_codigo = wait.until(EC.presence_of_element_located((By.ID, "seqCategoriaMovimentacao")))
        campo_codigo.clear()
        campo_codigo.send_keys("2011")
        time.sleep(2)

        wait.until(EC.element_to_be_clickable((By.ID, "btnBuscaMovimentacao"))).click()
        time.sleep(2)

        campo_obs = wait.until(EC.presence_of_element_located((By.ID, "observacao")))
        observacao = (
            f"RECEBIDO Ofício ref: {assunto} em {data_resposta} - "
            f"{hora_resposta} hs, por: {remetente}"
        )
        observacao = re.sub(r"\s+", " ", observacao).strip()[:1500]
        campo_obs.clear()
        _digitar_devagar(observacao, campo_obs)

        driver.execute_script("window.scrollBy(0, 567);")
        wait.until(EC.element_to_be_clickable((By.ID, "Concluir"))).click()
        time.sleep(2)

        alert = WebDriverWait(driver, 10).until(EC.alert_is_present())
        print(f"  [Projudi] Alerta: {alert.text}")
        alert.accept()

        print("  ✅ Acuse registrado no Projudi!")
        return True

    except Exception as exc:
        print(f"  ❌ Erro ao registrar acuse no Projudi: {exc}")
        return False

    finally:
        time.sleep(2)
        driver.quit()


# ════════════════════════════════════════════════════════════════════════════
# FLUXOS DE PROCESSAMENTO
# ════════════════════════════════════════════════════════════════════════════

def processar_encaminhamento(
    msg,
    msg_ids_processados: set,
    dados: list[dict],
    path_csv: str,
) -> bool:
    """
    Fluxo A: encaminha e-mails com PDFs para o cartório interno.

    Garante que cada e-mail (identificado por msg_id) seja encaminhado
    SOMENTE UMA VEZ, mesmo que o programa seja executado múltiplas vezes.

    Args:
        msg:                  Mensagem lida pelo imap_tools.
        msg_ids_processados:  Conjunto de msg_ids já registrados no CSV.
        dados:                Lista de registros do CSV (modificada in-place).
        path_csv:             Caminho do arquivo CSV.

    Returns:
        True se o e-mail foi encaminhado nesta execução.
    """
    msg_id = str(getattr(msg, "uid", "") or getattr(msg, "message_id", "")).strip()

    # ─── VERIFICAÇÃO CENTRAL: já encaminhamos antes? ────────────────────────
    if msg_id in msg_ids_processados:
        return False  # Ignorar silenciosamente

    # Tem PDF novo (não ignorado)?
    if not tem_pdf_novo(msg, msg_ids_processados):
        return False

    # Encaminha
    sucesso = encaminhar_email_com_pdfs(msg)
    if not sucesso:
        return False

    # Descobre o nome do PDF principal para registro
    nome_pdf = next(
        (a.filename for a in msg.attachments
         if (a.filename or "").lower().endswith(".pdf")
         and a.filename not in CONFIG["pdfs_ignorados"]),
        ""
    )

    # Salva IMEDIATAMENTE no CSV para evitar reencaminhamento
    registrar_encaminhamento_no_csv(
        path_csv=path_csv,
        dados=dados,
        msg_id=msg_id,
        remetente=msg.from_,
        assunto=msg.subject or "(sem assunto)",
        nome_pdf=nome_pdf,
    )

    # Atualiza o conjunto em memória para esta execução
    msg_ids_processados.add(msg_id)
    return True


def processar_resposta_projudi(
    msg,
    mapa_assuntos: dict,
    dados: list[dict],
    path_csv: str,
) -> bool:
    """
    Fluxo B: detecta resposta a um ofício enviado e registra o acuse no Projudi.

    Compara o assunto do e-mail recebido com os assuntos registrados no CSV.
    Se houver correspondência e o status ainda não for final, realiza a juntada.

    Args:
        msg:           Mensagem recebida.
        mapa_assuntos: Dicionário {assunto_normalizado: linha_csv}.
        dados:         Lista de registros (modificada in-place).
        path_csv:      Caminho do CSV.

    Returns:
        True se a juntada foi realizada.
    """
    assunto_msg = _normalizar_assunto(msg.subject or "")

    # Verifica se corresponde a algum ofício enviado
    if assunto_msg not in mapa_assuntos:
        return False

    row = mapa_assuntos[assunto_msg]

    # Já foi processado?
    if row.get("registrar_envio", "").strip().lower() in STATUS_FINAIS:
        return False

    # Extrai texto da resposta
    texto_html  = BeautifulSoup(msg.html, "html.parser").get_text() if msg.html else ""
    texto_resp  = msg.text or texto_html or ""
    texto_resp  = _limpar_cid(texto_resp)
    texto_resp  = re.sub(r"\s+", " ", texto_resp).strip()[:100]

    data_resp  = msg.date.strftime("%d/%m/%Y") if msg.date else datetime.now().strftime("%d/%m/%Y")
    hora_resp  = msg.date.strftime("%H:%M:%S") if msg.date else datetime.now().strftime("%H:%M:%S")

    assunto_juntada = (
        row["assunto"].split("Referente")[0].strip() + " - " + texto_resp.strip()
    )

    sucesso = registrar_acuse_projudi(
        url_recebimento=row["url_recebimento"],
        assunto=assunto_juntada,
        remetente=msg.from_,
        data_resposta=data_resp,
        hora_resposta=hora_resp,
    )

    if sucesso:
        # Atualiza a linha em memória
        row["status"]          = "recebido"
        row["resposta"]        = texto_resp
        row["registrar_envio"] = "cumprido"

        # Atualiza também na lista dados (mesma referência, mas garantimos)
        for linha in dados:
            if linha.get("assunto", "").strip() == row.get("assunto", "").strip():
                linha["status"]          = "recebido"
                linha["resposta"]        = texto_resp
                linha["registrar_envio"] = "cumprido"
                break

        salvar_dados_csv(path_csv, dados)

    return sucesso


# ════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Ponto de entrada principal do script de recebimento."""
    path_csv = CONFIG["path_csv"]

    print("=" * 60)
    print("  RECEBIMENTO DE RESPOSTAS – 2ª VSJ")
    print("=" * 60)

    # Carrega dados e estruturas auxiliares
    dados               = carregar_dados_csv(path_csv)
    msg_ids_processados = carregar_msg_ids_encaminhados(path_csv)
    mapa_assuntos       = carregar_mapa_assuntos(path_csv)

    print(f"[INFO] {len(dados)} registros no CSV.")
    print(f"[INFO] {len(msg_ids_processados)} msg_ids já encaminhados (não serão reprocessados).")
    print(f"[INFO] {len(mapa_assuntos)} ofícios no mapa de assuntos.")

    encaminhados  = 0
    acuses        = 0
    ignorados     = 0

    with MailBox(CONFIG["imap_server"]).login(
        CONFIG["usuario"], CONFIG["senha_app"], initial_folder="INBOX"
    ) as mailbox:

        mensagens = list(
            mailbox.fetch(criteria=A(all=True), reverse=True, limit=CONFIG["limite_emails"])
        )
        print(f"[INFO] {len(mensagens)} e-mails lidos da caixa de entrada.\n")

        for msg in mensagens:
            msg_id  = str(getattr(msg, "uid", "") or getattr(msg, "message_id", "")).strip()
            assunto = msg.subject or "(sem assunto)"

            print(f"  → {assunto[:60]}")

            # Fluxo A: encaminhar PDF para cartório (somente uma vez)
            if processar_encaminhamento(msg, msg_ids_processados, dados, path_csv):
                encaminhados += 1
                continue  # Se encaminhou, não tenta também registrar acuse

            # Fluxo B: registrar acuse de resposta no Projudi
            if processar_resposta_projudi(msg, mapa_assuntos, dados, path_csv):
                acuses += 1
            else:
                ignorados += 1

    # Salva o estado final
    salvar_dados_csv(path_csv, dados)

    print("\n" + "=" * 60)
    print(f"  ✅ Encaminhamentos realizados : {encaminhados}")
    print(f"  ✅ Acuses registrados (Projudi): {acuses}")
    print(f"  ℹ️  E-mails ignorados/já proc. : {ignorados}")
    print("=" * 60)


if __name__ == "__main__":
    main()
