"""邮件提醒。需要的环境变量（放在 GitHub Secrets）：
SMTP_USER、SMTP_PASSWORD、MAIL_TO；可选 SMTP_HOST（默认 smtp.gmail.com）、SMTP_PORT（默认 465）。
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

log = logging.getLogger(__name__)

STATE_CN = {"green": "绿", "yellow": "黄", "red": "红"}


def diff_states(prev: dict | None, cur: dict) -> list[str]:
    """返回需要提醒的变化；prev 为空表示首次运行。"""
    if not prev:
        return ["首次运行，以下为当前状态"]
    changes = []
    for key, label in (("liquidity", "流动性开关"), ("narrative", "叙事开关")):
        if prev.get(key) != cur.get(key):
            changes.append(f"{label}：{STATE_CN.get(prev.get(key), '?')} → {STATE_CN[cur[key]]}")
    if prev.get("stage") != cur.get("stage"):
        changes.append(f"阶段：{prev.get('stage')} → {cur['stage']}")
    new_hard = sorted(set(cur.get("hard", [])) - set(prev.get("hard", [])))
    cleared = sorted(set(prev.get("hard", [])) - set(cur.get("hard", [])))
    changes += [f"硬性风控开关触发：{h}" for h in new_hard]
    changes += [f"硬性风控开关解除：{h}" for h in cleared]
    return changes


def compose(changes: list[str], dash: dict, site_url: str | None) -> tuple[str, str]:
    reg = dash["regime"]
    subject = (f"[美股阶段] {reg['action']['stage']}｜叙事{STATE_CN[reg['narrative']['state']]}"
               f" 流动性{STATE_CN[reg['liquidity']['state']]}")
    lines = ["变化：", *[f"  · {c}" for c in changes], "",
             f"建议：{reg['action']['action']}（参考仓位 {reg['action']['position']}）", ""]
    lines.append(f"叙事开关（{reg['narrative']['primary']}）：{STATE_CN[reg['narrative']['state']]}")
    lines += [f"  · {r}" for r in reg["narrative"]["reasons"]] or ["  · 无异常"]
    lines.append(f"流动性开关：{STATE_CN[reg['liquidity']['state']]}")
    lines += [f"  · {r}" for r in reg["liquidity"]["reasons"]] or ["  · 无异常"]
    upcoming = [e for e in dash.get("calendar", []) if e.get("importance") == "high"][:5]
    if upcoming:
        lines += ["", "近期重要事件："] + [f"  · {e['date']} {e['name']}" for e in upcoming]
    if site_url:
        lines += ["", f"查看 dashboard：{site_url}"]
    lines += ["", f"数据时间：{dash['generated_at']}（仅供参考，不构成投资建议）"]
    return subject, "\n".join(lines)


def send(subject: str, body: str) -> bool:
    user, password, to = (os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"))
    if not (user and password and to):
        log.info("未配置邮箱，跳过发送。主题：%s", subject)
        return False
    # 没填的 secret 在 Actions 里是空字符串，不能直接 int()
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("美股 Dashboard", user))
    msg["To"] = to
    with smtplib.SMTP_SSL(host, port, timeout=30) as server:
        server.login(user, password)
        server.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    log.info("已发送邮件：%s", subject)
    return True
