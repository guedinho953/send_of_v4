from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

import os
import re
import smtplib
import time
from email.message import EmailMessage

from imap_tools import MailBox, A
from bs4 import BeautifulSoup
from projudi.models import OficioRecord, OficioLog

GMAIL_USER = os.getenv("GMAIL_USER", "pafonso.2vsj@gmail.com")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASS", "ouysuorpvqprfqig")
DESTINATARIO_INTERNO = "pafonso-2vsj@tjba.jus.br"
LIMITE_EMAILS = 100
LINK_BASE = "https://projudi.tjba.jus.br/projudi/"

PDFS_IGNORADOS = {
    "3.Sgt PM Kelson e Sgt PM Marilson 204.2025.sec_0001.pdf",
    "Oficio_00126551581.pdf",
    "Extrato_00122965493_2VSJ_SGT_SANTOS.pdf",
    "ADILSON MOREIRA_0001.pdf",
    "Oficio_00124493202.pdf",
    "Requerimento_0087935422_EMAIL_1.pdf",
    "Oficio_00122965336.pdf",
}


def _normalizar_assunto(assunto: str) -> str:
    assunto = assunto.lower().strip()
    assunto = re.sub(r"^(re|res|enc|fwd|fw)\s*:\s*", "", assunto)
    return assunto.strip()


def _limpar_cid(texto: str) -> str:
    texto = re.sub(r"\[cid:[^\]]+\]", "", texto)
    texto = re.sub(r"[_\-—━]{10,}", "", texto)
    return texto


def _limpar_remetente(remetente: str) -> str:
    m = re.search(r'<([^>]+@[^>]+)>', remetente)
    if m:
        return m.group(1)
    return remetente.strip()


def get_msg_id(msg) -> str:
    raw = (msg.headers.get("message-id") or [""]) if hasattr(msg, "headers") else [""]
    msg_id = (raw[0] if isinstance(raw, list) else str(raw)).strip().strip("<>")
    if not msg_id:
        msg_id = str(msg.uid or "").strip()
    return msg_id


class Command(BaseCommand):
    help = "Recebe respostas de oficios via Gmail, encaminha PDFs e registra acuse no Projudi"

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=LIMITE_EMAILS)
        parser.add_argument("--apenas-encaminhar", action="store_true")
        parser.add_argument("--apenas-acuse", action="store_true")


    def handle(self, *args, **options):
        limite = options["limite"]

        self.stdout.write("=" * 60)
        self.stdout.write(self.style.MIGRATE_HEADING("  RECEBIMENTO DE RESPOSTAS – 2ª VSJ (Django)"))
        self.stdout.write("=" * 60)

        msg_ids_encaminhados = self._carregar_msg_ids_encaminhados()
        mapa_assuntos = self._carregar_mapa_assuntos()

        self.stdout.write(f"[INFO] {OficioRecord.objects.count()} oficios no banco")
        self.stdout.write(f"[INFO] {len(msg_ids_encaminhados)} msg_ids ja encaminhados")
        self.stdout.write(f"[INFO] {len(mapa_assuntos)} oficios no mapa de assuntos")

        encaminhados = 0
        acuses = 0
        ignorados = 0

        with MailBox("imap.gmail.com").login(
            GMAIL_USER, GMAIL_APP_PASS, initial_folder="INBOX"
        ) as mailbox:
            mensagens = list(
                mailbox.fetch(criteria=A(all=True), reverse=True, limit=limite)
            )
            self.stdout.write(f"[INFO] {len(mensagens)} e-mails lidos\n")

            for msg in mensagens:
                msg_id = get_msg_id(msg)
                assunto_msg = _normalizar_assunto(msg.subject or "")
                self.stdout.write(f"  → {(msg.subject or '(sem assunto)')[:60]}")

                # Identifica oficio correspondente (multiplas estrategias)
                oficio = self._encontrar_oficio_por_email(msg, mapa_assuntos)

                # Fluxo A: Encaminhamento (sempre que houver PDF novo)
                encaminhou = False
                if not options["apenas_acuse"]:
                    encaminhou = self._processar_encaminhamento(msg, msg_id, msg_ids_encaminhados, oficio)
                    if encaminhou:
                        encaminhados += 1
                        mapa_assuntos = self._carregar_mapa_assuntos()

                # Fluxo B: Salva retorno no banco como pendente (se o email responde a um oficio)
                if oficio and not options["apenas_encaminhar"]:
                    if self._processar_acuse(msg, msg_id, oficio):
                        acuses += 1
                    else:
                        ignorados += 1

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"  Encaminhamentos realizados  : {encaminhados}")
        self.stdout.write(f"  Acuses registrados (Projudi): {acuses}")
        self.stdout.write(f"  E-mails ignorados           : {ignorados}")
        self.stdout.write("=" * 60)

    # ------------------------------------------------------------------
    # Controle de duplicidade via OficioLog
    # ------------------------------------------------------------------
    def _carregar_msg_ids_encaminhados(self) -> set:
        logs = OficioLog.objects.filter(
            tipo="resposta", mensagem__startswith="ENCAMINHADO:"
        ).values_list("detalhes", flat=True)
        msg_ids = set()
        for detalhes in logs:
            if isinstance(detalhes, dict) and "msg_id" in detalhes:
                msg_ids.add(detalhes["msg_id"])
        return msg_ids

    def _carregar_mapa_assuntos(self) -> dict:
        mapa = {}
        for oficio in OficioRecord.objects.exclude(assunto=""):
            chave = _normalizar_assunto(oficio.assunto)
            if chave:
                mapa[chave] = oficio
            # Tambem indexa pelo subject padronizado "Oficio - nº XXX/2026 - SEC"
            # para casar com replies do novo formato
            chave_nova = _normalizar_assunto(f"Oficio - n\xba {oficio.numero_oficio}")
            if chave_nova and chave_nova != chave:
                mapa[chave_nova] = oficio
        return mapa

    def _encontrar_oficio_por_email(self, msg, mapa_assuntos: dict):
        """
        Tenta encontrar oficio correspondente ao email por multiplas estrategias:
        1. Assunto normalizado (exato)
        2. Nº processo CNJ no assunto
        3. Nº oficio no assunto
        """
        assunto_msg = _normalizar_assunto(msg.subject or "")
        if not assunto_msg:
            return None

        oficio = mapa_assuntos.get(assunto_msg)
        if oficio:
            return oficio

        cnj = re.search(r'\d{7,20}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', msg.subject or '')
        if cnj:
            oficio = OficioRecord.objects.filter(numero_processo_cnj=cnj.group(0)).first()
            if oficio:
                self.stdout.write(f"  Match por CNJ: {cnj.group(0)}")
                return oficio

        num = re.search(r'(\d{2,3})/(\d{4})', msg.subject or '')
        if num:
            match = OficioRecord.objects.filter(numero_oficio__startswith=num.group(0)).first()
            if match:
                self.stdout.write(f"  Match por nº oficio: {num.group(0)}")
                return match

        return None

    # ------------------------------------------------------------------
    # Fluxo A: Encaminhamento
    # ------------------------------------------------------------------
    def _tem_pdf_novo(self, msg, msg_id: str, msg_ids_processados: set) -> bool:
        if msg_id in msg_ids_processados:
            return False
        for anexo in msg.attachments:
            nome = (anexo.filename or "").strip()
            if nome.lower().endswith(".pdf") and nome not in PDFS_IGNORADOS:
                return True
        return False

    def _sanitizar_header(self, valor: str) -> str:
        """Remove caracteres de quebra de linha de valores de header de email."""
        return valor.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()

    def _encaminhar_email(self, msg) -> bool:
        email = EmailMessage()
        assunto_seguro = self._sanitizar_header(msg.subject or "(sem assunto)")
        email["Subject"] = f"Enc: {assunto_seguro}"
        email["From"] = GMAIL_USER
        email["To"] = DESTINATARIO_INTERNO

        corpo_original = msg.text or (
            BeautifulSoup(msg.html, "html.parser").get_text() if msg.html else "(sem conteudo)"
        )
        data_fmt = msg.date.strftime("%d/%m/%Y %H:%M") if msg.date else "data desconhecida"
        pdfs = [a.filename for a in msg.attachments if (a.filename or "").lower().endswith(".pdf")]

        corpo = (
            f"Encaminhado automaticamente.\n\n"
            f"{'─' * 40}\n"
            f"Remetente original: {msg.from_}\n"
            f"Data: {data_fmt}\n"
            f"Assunto original: {msg.subject}\n"
            f"PDFs: {pdfs}\n"
            f"{'─' * 40}\n\n"
            f"{corpo_original}"
        )
        email.set_content(corpo)

        for anexo in msg.attachments:
            nome = anexo.filename or ""
            if nome.lower().endswith(".pdf"):
                email.add_attachment(
                    anexo.payload, maintype="application", subtype="pdf", filename=nome,
                )

        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
                smtp.starttls()
                smtp.login(GMAIL_USER, GMAIL_APP_PASS)
                smtp.send_message(email)
            return True
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Erro ao encaminhar: {exc}"))
            return False

    def _processar_encaminhamento(self, msg, msg_id: str, msg_ids_processados: set, oficio=None) -> bool:
        if msg_id in msg_ids_processados:
            return False
        if not self._tem_pdf_novo(msg, msg_id, msg_ids_processados):
            return False

        self.stdout.write("  [Fluxo A] Encaminhando com PDFs...")
        sucesso = self._encaminhar_email(msg)
        if not sucesso:
            return False

        nome_pdf = next(
            (a.filename for a in msg.attachments
             if (a.filename or "").lower().endswith(".pdf")
             and a.filename not in PDFS_IGNORADOS),
            ""
        )

        assunto_msg = _normalizar_assunto(msg.subject or "")
        mapa = self._carregar_mapa_assuntos()
        oficio = mapa.get(assunto_msg)

        OficioLog.objects.create(
            oficio=oficio,
            tipo="resposta",
            mensagem=f"ENCAMINHADO: {nome_pdf}",
            detalhes={"msg_id": msg_id, "remetente": msg.from_, "assunto": msg.subject},
        )
        msg_ids_processados.add(msg_id)
        self.stdout.write(self.style.SUCCESS(f"  ️ Encaminhado para {DESTINATARIO_INTERNO}"))
        return True

    # ------------------------------------------------------------------
    # Fluxo B: Salva retorno + Acuse no Projudi (via OficioService)
    # ------------------------------------------------------------------
    def _processar_acuse(
        self, msg, msg_id: str, oficio=None
    ) -> bool:
        if not oficio:
            return False

        if oficio.status_retorno != "sem_retorno":
            return False

        # Ja registramos resposta para este msg_id?
        if OficioLog.objects.filter(
            oficio=oficio, tipo="resposta", mensagem__startswith="ACUSE:"
        ).exists():
            return False

        texto_html = BeautifulSoup(msg.html, "html.parser").get_text() if msg.html else ""
        texto_resp = msg.text or texto_html or ""
        texto_resp = _limpar_cid(texto_resp)
        texto_resp = re.sub(r"\s+", " ", texto_resp).strip()[:250]
        texto_resp = f"Assunto: {msg.subject or '(sem assunto)'}\n\n{texto_resp}"[:300]

        data_resp = msg.date if msg.date else timezone.now()

        # --- Salva retorno no banco como pendente (sem acuse automatico) ---
        oficio.status_retorno = "recebido"
        oficio.data_retorno = data_resp
        oficio.remetente_retorno = _limpar_remetente(msg.from_ or "")
        oficio.assunto_retorno = self._sanitizar_header(msg.subject or "")[:300]
        oficio.conteudo_retorno = texto_resp
        anexos = [
            {"nome": a.filename, "tipo": a.content_type}
            for a in msg.attachments
        ]
        oficio.anexos_retorno = anexos
        oficio.observacao_retorno = f"Retorno salvo do email ({msg_id[:30]}...)"
        oficio.save(update_fields=[
            "status_retorno", "data_retorno", "remetente_retorno",
            "assunto_retorno", "conteudo_retorno", "anexos_retorno",
            "observacao_retorno",
        ])

        OficioLog.objects.create(
            oficio=oficio,
            tipo="resposta",
            mensagem=f"Resposta recebida de {msg.from_}",
            detalhes={
                "msg_id": msg_id,
                "remetente": msg.from_,
                "assunto": msg.subject,
                "conteudo_resumo": texto_resp[:200],
                "aguardando_juntada": True,
            },
        )

        self.stdout.write(self.style.SUCCESS(f"  Resposta salva! Pendente de juntada no Projudi."))

        return True  # retorno salvo no banco


