# -*- coding: utf-8 -*-
"""SMTP 邮件发送（QQ 邮箱：smtp.qq.com:465 SSL，密码填授权码）。

所有敏感信息只从环境变量读取，禁止硬编码：
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / MAIL_TO / MAIL_FROM(可选)
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr


def smtp_settings():
    host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    to_raw = os.environ.get("MAIL_TO", "")
    sender = os.environ.get("MAIL_FROM", "") or user
    recipients = [x.strip() for x in to_raw.replace(";", ",").split(",") if x.strip()]
    return host, port, user, password, sender, recipients


def smtp_configured() -> bool:
    _, _, user, password, _, recipients = smtp_settings()
    return bool(user and password and recipients)


def send_email(subject: str, html_body: str, text_body: str = "") -> None:
    host, port, user, password, sender, recipients = smtp_settings()
    if not (user and password and recipients):
        raise RuntimeError("SMTP 环境变量缺失（SMTP_USER/SMTP_PASS/MAIL_TO），无法发送邮件")

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("资讯日报", "utf-8")), sender))
    msg["To"] = ", ".join(recipients)

    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=context)
    try:
        server.login(user, password)
        server.sendmail(sender, recipients, msg.as_string())
    finally:
        server.quit()


def send_error_email(title: str, detail: str) -> bool:
    """发送抓取失败提醒邮件；自身失败时返回 False，不影响主流程退出码。"""
    body = (
        '<div style="font-family:sans-serif;max-width:640px;margin:0 auto;">'
        '<div style="background:#d03050;color:#fff;padding:12px 16px;'
        'border-radius:8px 8px 0 0;font-weight:bold;">⚠ 资讯日报脚本报错提醒</div>'
        '<div style="border:1px solid #eee;border-top:0;border-radius:0 0 8px 8px;padding:14px 16px;">'
        f'<pre style="white-space:pre-wrap;font-size:13px;color:#333;">{_escape(detail)}</pre>'
        "</div></div>"
    )
    try:
        send_email(title, body)
        return True
    except Exception as e:  # noqa: BLE001 - 报错邮件本身失败只能打印
        print(f"[error-mail] 报错提醒邮件发送失败: {e}")
        return False


def _escape(text: str) -> str:
    import html
    return html.escape(str(text))
