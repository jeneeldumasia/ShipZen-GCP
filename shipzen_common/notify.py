"""Email notifications about deployments, sent with Resend (https://resend.com).

Recipients: the project's owners and editors who haven't turned emails off,
at their GitHub-verified address (users.email). Without RESEND_API_KEY nothing
is sent. Nothing here ever raises into the caller: a deploy must never fail
because an email couldn't be sent. Sending happens on a background thread.

Each (deployment, event) is mailed at most once (Redis SET NX), so the
controller's repeated reconcile sweeps and retries can't send duplicates.
"""
import html
import logging
import os
import threading

import requests

from shipzen_common.redact import redact

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
SENDER = os.getenv("NOTIFY_FROM", "ShipZen <notify@jeneeldumasia.codes>")
UI_URL = os.getenv("SHIPZEN_UI_URL", "https://shipzen.jeneeldumasia.codes").rstrip("/")
DEDUPE_SECONDS = 7 * 24 * 3600

EVENTS = {
    "live": ("is live", "Your deployment of {project} is live."),
    "failed": ("failed to deploy", "Your deployment of {project} failed."),
    "down": ("is down", "{project} stopped responding: its instances keep crashing."),
    "preview": ("preview is ready", "A preview of {project} for a pull request is ready."),
}


def _api_key() -> str:
    return os.getenv("RESEND_API_KEY", "").strip()


def recipients(cur, project_id: str) -> list[str]:
    """Owners and editors who want emails, by verified address."""
    cur.execute(
        """
        SELECT DISTINCT u.email FROM users u
        WHERE u.email IS NOT NULL AND u.email <> '' AND COALESCE(u.email_notifications, TRUE)
          AND (u.id = (SELECT owner_id FROM projects WHERE id = %s)
               OR u.id IN (SELECT user_id FROM project_members
                           WHERE project_id = %s AND role IN ('owner', 'editor')))
        """, (project_id, project_id))
    return sorted({row[0] for row in cur.fetchall()})


def compose(event: str, project: str, deployment: dict, detail: str = None) -> tuple[str, str, str]:
    """(subject, text, html) for one event."""
    short, lead = EVENTS[event]
    subject = f"{project} {short}"
    url = f"{UI_URL}/projects/{deployment['project_id']}/deployments/{deployment['deployment_id']}"
    lines = [lead.format(project=project)]
    if deployment.get("commit_sha"):
        msg = (deployment.get("commit_message") or "").splitlines()[0][:120] if deployment.get("commit_message") else ""
        lines.append(f"Commit {deployment['commit_sha'][:7]}" + (f": {msg}" if msg else ""))
    if deployment.get("branch"):
        lines.append(f"Branch: {deployment['branch']}")
    if detail:
        lines.append("")
        lines.append(redact(detail)[:1500])
    lines += ["", f"Details: {url}", "", "You get these emails as an owner or editor of this project. "
              "Turn them off with the bell icon in ShipZen's top bar."]
    text = "\n".join(lines)
    body = "<br>".join(html.escape(line) for line in lines[:-3])
    html_body = (f"<div style=\"font-family:system-ui,sans-serif;font-size:14px;line-height:1.5\">{body}"
                 f"<p><a href=\"{html.escape(url)}\">Open the deployment</a></p>"
                 f"<p style=\"color:#888;font-size:12px\">You get these emails as an owner or editor of this "
                 f"project. Turn them off with the bell icon in ShipZen's top bar.</p></div>")
    return subject, text, html_body


def send_email(to: list[str], subject: str, text: str, html_body: str) -> bool:
    key = _api_key()
    if not key or not to:
        return False
    try:
        r = requests.post(RESEND_URL, timeout=10,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"from": SENDER, "to": to, "subject": subject, "text": text, "html": html_body})
        if r.status_code >= 300:
            logger.warning(f"Resend refused an email: HTTP {r.status_code} {redact(r.text[:200])}")
            return False
        return True
    except Exception as e:
        logger.warning(f"Could not send email: {type(e).__name__}")
        return False


def _in_background(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def notify_deployment(conn, redis_client, deployment_id: str, event: str, detail: str = None) -> None:
    """Email the project's owners/editors about a deployment event, once. Never raises."""
    if event not in EVENTS or not _api_key():
        return
    try:
        if redis_client is not None and not redis_client.set(
                f"shipzen:notified:{deployment_id}:{event}", "1", nx=True, ex=DEDUPE_SECONDS):
            return
        with conn.cursor() as cur:
            cur.execute(
                "SELECT d.deployment_id, d.project_id, d.commit_sha, d.commit_message, d.branch, p.name "
                "FROM deployments d JOIN projects p ON p.id = d.project_id WHERE d.deployment_id = %s;",
                (deployment_id,))
            row = cur.fetchone()
            if not row:
                return
            dep = dict(zip(("deployment_id", "project_id", "commit_sha", "commit_message", "branch", "name"), row))
            to = recipients(cur, dep["project_id"])
        if not to:
            return
        subject, text, html_body = compose(event, dep["name"], dep, detail)
        _in_background(send_email, to, subject, text, html_body)
    except Exception as e:
        logger.warning(f"Could not prepare the {event} email for {deployment_id}: {type(e).__name__}")
