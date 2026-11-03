"""Sends alert emails through the mail server set in backend/.env."""
import smtplib
from email.message import EmailMessage

from . import config

TIMEOUT_SECONDS = 20


def recipients():
    return [address.strip() for address in (config.ALERT_EMAIL_TO or "").split(",") if address.strip()]


def is_configured():
    return bool(config.SMTP_HOST and recipients())


def _connect():
    if config.SMTP_PORT == 465:
        return smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_SECONDS)
    server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_SECONDS)
    if config.SMTP_TLS:
        server.starttls()
    return server


def send_alert_email(alerts):
    """Sends one email listing these alerts. Raises an error if it can't be sent."""
    message = EmailMessage()
    message["Subject"] = "EarthScape: %d new alert%s" % (len(alerts), "" if len(alerts) == 1 else "s")
    message["From"] = config.SMTP_FROM or config.SMTP_USER or "earthscape@localhost"
    message["To"] = ", ".join(recipients())
    lines = ["[%s] %s\n    Measured: %s" % (alert["severity"], alert["title"], alert["value"]) for alert in alerts]
    message.set_content("\n\n".join(lines) + "\n\nLive values are model estimates from Open-Meteo.\n")
    with _connect() as server:
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
        server.send_message(message)
