import json
import logging
import smtplib
import urllib.request
from email.message import EmailMessage

from sqlalchemy.orm import Session

from . import config
from .db import Notification

log = logging.getLogger('notify')


def channels():
    return {
        'email': bool(config.SMTP_HOST and config.NOTIFY_EMAIL),
        'webhook': bool(config.NOTIFY_WEBHOOK_URL),
    }


def _email(subject, body):
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = subject, config.SMTP_FROM, config.NOTIFY_EMAIL
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as s:
        s.starttls()
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)


def _webhook(text):
    # 'text' is read by Slack, 'content' by Discord.
    req = urllib.request.Request(config.NOTIFY_WEBHOOK_URL, data=json.dumps({'text': text, 'content': text}).encode(),
                                 headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=10).close()


def send(db: Session, kind: str, subject: str, body: str):
    delivered = []
    on = channels()
    for name, fn in (('email', lambda: _email(subject, body)), ('webhook', lambda: _webhook(f'{subject}\n{body}'))):
        if not on[name]:
            continue
        try:
            fn()
            delivered.append(name)
        except Exception:  # a failed notification must never fail the writer's save
            log.exception('notification via %s failed', name)
    db.add(Notification(kind=kind, message=f'{subject}\n{body}', delivered=','.join(delivered) or None))
    db.commit()
    return delivered
