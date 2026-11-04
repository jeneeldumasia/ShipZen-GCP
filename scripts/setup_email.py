#!/usr/bin/env python3
"""One-time setup for email notifications (run by .github/workflows/setup-email.yaml).

1. Adds the sending domain to Resend (or finds it if it's already there).
2. Writes the DNS records Resend asks for (DKIM, SPF, bounce MX) to Cloudflare,
   skipping records that already exist. They persist across platform teardowns.
3. Asks Resend to verify the domain and reports the status.

Env: RESEND_API_KEY (a full-access key), CLOUDFLARE_API_TOKEN (DNS edit),
     EMAIL_DOMAIN (default jeneeldumasia.codes). Secrets are never printed.
Only the standard library is used, so it runs on a bare GitHub runner.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

DOMAIN = os.getenv("EMAIL_DOMAIN", "jeneeldumasia.codes")
RESEND = "https://api.resend.com"
CF = "https://api.cloudflare.com/client/v4"


def call(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "User-Agent": "shipzen-setup-email"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def fail(msg):
    print(f"::error::{msg}")
    sys.exit(1)


def resend_domain(key):
    status, body = call("GET", f"{RESEND}/domains", key)
    if status in (401, 403):
        fail("Resend rejected the API key. setup needs a key with Full access "
             "(Resend > API Keys); the platform itself only needs Sending access.")
    if status != 200:
        fail(f"Resend: listing domains failed (HTTP {status}).")
    for d in body.get("data", []):
        if d.get("name") == DOMAIN:
            print(f"Resend: {DOMAIN} already added (status: {d.get('status')}).")
            return d["id"]
    status, body = call("POST", f"{RESEND}/domains", key, {"name": DOMAIN})
    if status not in (200, 201):
        fail(f"Resend: adding {DOMAIN} failed (HTTP {status}): {body.get('message', '')}")
    print(f"Resend: added {DOMAIN}.")
    return body["id"]


def main():
    key = os.environ.get("RESEND_API_KEY", "").strip()
    cf = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not key:
        fail("RESEND_API_KEY repository secret is not set.")
    if not cf:
        fail("CLOUDFLARE_API_TOKEN repository secret is not set.")

    domain_id = resend_domain(key)
    status, domain = call("GET", f"{RESEND}/domains/{domain_id}", key)
    if status != 200:
        fail(f"Resend: reading the domain failed (HTTP {status}).")
    records = domain.get("records", [])

    status, zones = call("GET", f"{CF}/zones?name={DOMAIN}", cf)
    if status != 200 or not zones.get("result"):
        fail(f"Cloudflare: zone {DOMAIN} not found with this token.")
    zone = zones["result"][0]["id"]

    for rec in records:
        rtype = rec["type"].upper()
        name = rec["name"] if rec["name"].endswith(DOMAIN) else f"{rec['name']}.{DOMAIN}"
        content = rec["value"]
        status, existing = call("GET", f"{CF}/zones/{zone}/dns_records?type={rtype}&name={name}", cf)
        if any(r.get("content", "").strip('"') == content.strip('"') for r in existing.get("result", [])):
            print(f"Cloudflare: {rtype} {name} already present.")
            continue
        body = {"type": rtype, "name": name, "content": content, "ttl": 1, "proxied": False}
        if rtype == "MX":
            body["priority"] = int(rec.get("priority") or 10)
        status, res = call("POST", f"{CF}/zones/{zone}/dns_records", cf, body)
        if status not in (200, 201) or not res.get("success"):
            errs = "; ".join(e.get("message", "") for e in res.get("errors", []))
            fail(f"Cloudflare: creating {rtype} {name} failed (HTTP {status}): {errs}")
        print(f"Cloudflare: created {rtype} {name}.")

    call("POST", f"{RESEND}/domains/{domain_id}/verify", key)
    for _ in range(12):
        time.sleep(10)
        _, d = call("GET", f"{RESEND}/domains/{domain_id}", key)
        if d.get("status") == "verified":
            print(f"Resend: {DOMAIN} is verified. Emails can be sent from notify@{DOMAIN}.")
            return
    print(f"Resend: {DOMAIN} is '{d.get('status')}'. DNS can take a while; Resend keeps "
          "checking on its own. Re-run this workflow later to see the status.")


if __name__ == "__main__":
    main()
