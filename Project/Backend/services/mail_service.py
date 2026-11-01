from email.message import EmailMessage
import smtplib
from pathlib import Path
from ..core.config import get_settings


def send_email(recipient: str, subject: str, html: str) -> None:
    s = get_settings()
    message = EmailMessage()
    message["From"] = f"{s.mail_from_name} <{s.mail_from_address}>"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("Please view this message in an HTML-capable email client.")
    message.add_alternative(html, subtype="html")
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as server:
        if s.smtp_use_tls:
            server.starttls()
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(message)


def exam_invite_html(company_name: str, job_title: str, link: str) -> str:
    template = Path(__file__).resolve().parents[1] / "mail_templates" / "exam_invite.html"
    return template.read_text(encoding="utf-8").format(company_name=company_name, job_title=job_title, link=link)
