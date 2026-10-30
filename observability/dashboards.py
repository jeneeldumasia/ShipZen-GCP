#!/usr/bin/env python3
"""Generate ShipZen's Grafana dashboards.

    python observability/dashboards.py   # rewrites infra/system/grafana-dashboards.yaml

Dashboards are written here, as code, rather than exported from the Grafana UI:
it keeps every query reviewable, and a test checks the generated file is in
sync. Edit this file, run it, commit both.

Audience rules for the "ShipZen" folder: someone who has never heard of
Kubernetes should be able to answer "is it working?", "is my app OK?" and
"are deploys going through?" without reading a query. So: plain titles,
a description on every panel (hover the (i)), green/red rather than raw
numbers where possible, and no panel that only an operator could interpret.
Operator detail lives in the separate "ShipZen (technical)" folder.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "infra/system/grafana-dashboards.yaml"

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

# Every tenant namespace gets a ResourceQuota called tenant-quota (controller/templates/tenant.yaml.j2),
# so "and on(namespace) TENANTS" limits any query to user apps.
TENANTS = 'kube_resourcequota{resourcequota="tenant-quota",resource="pods",type="hard"}'
# Envoy names each upstream cluster "httproute/<namespace>/<route>/rule/<n>"; lift the namespace out.
def by_app(expr: str) -> str:
    return f'label_replace({expr}, "namespace", "$1", "envoy_cluster_name", "httproute/([^/]+)/.*")'

GREEN, ORANGE, RED, BLUE = "green", "orange", "red", "blue"


# ── panel helpers ────────────────────────────────────────────────────────────

def _thresholds(steps):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}


def _target(expr, legend="", instant=False, fmt="time_series", ref="A"):
    t = {"datasource": PROM, "expr": expr, "refId": ref, "legendFormat": legend or "__auto"}
    if instant:
        t.update({"instant": True, "range": False})
    if fmt != "time_series":
        t["format"] = fmt
    return t


def text(content, h=3):
    return {"type": "text", "title": "", "transparent": True, "h": h,
            "options": {"mode": "markdown", "content": content}}


def row(title):
    return {"type": "row", "title": title, "collapsed": False, "panels": [], "h": 1, "w": 24}


UP_MAPPINGS = [
    {"type": "value", "options": {"0": {"text": "Down", "color": RED, "index": 0},
                                  "1": {"text": "Working", "color": GREEN, "index": 1}}},
    {"type": "special", "options": {"match": "null", "result": {"text": "No signal", "color": ORANGE, "index": 2}}},
]


def status(title, expr, description, w=3, h=4):
    """Green 'Working' / red 'Down' tile. expr must evaluate to 1 or 0."""
    return {
        "type": "stat", "title": title, "description": description, "w": w, "h": h,
        "targets": [_target(expr, instant=True)],
        "fieldConfig": {"defaults": {"mappings": UP_MAPPINGS, "thresholds": _thresholds([(None, RED), (1, GREEN)]),
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"colorMode": "background", "graphMode": "none", "textMode": "value", "justifyMode": "center",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    }


def stat(title, expr, description, unit="none", steps=((None, BLUE),), w=4, h=4, decimals=0,
         no_value="0", mappings=None, graph=False):
    return {
        "type": "stat", "title": title, "description": description, "w": w, "h": h,
        "targets": [_target(expr, instant=not graph)],
        "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals, "noValue": no_value,
                                     "mappings": mappings or [], "thresholds": _thresholds(steps),
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"colorMode": "value", "graphMode": "area" if graph else "none", "textMode": "value",
                    "justifyMode": "center",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    }


def gauge(title, expr, description, w=6, h=6):
    return {
        "type": "gauge", "title": title, "description": description, "w": w, "h": h,
        "targets": [_target(expr, instant=True)],
        "fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 1, "decimals": 0,
                                     "thresholds": _thresholds([(None, GREEN), (0.7, ORANGE), (0.9, RED)]),
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"showThresholdMarkers": True, "showThresholdLabels": False,
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    }


def graph(title, targets, description, unit="none", w=12, h=8, stack=False, colors=None, bars=False, decimals=None,
          max_=None):
    overrides = [{"matcher": {"id": "byName", "options": name},
                  "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
                 for name, c in (colors or {}).items()]
    defaults = {"unit": unit, "min": 0,
                "custom": {"drawStyle": "bars" if bars else "line", "fillOpacity": 60 if bars else 15,
                           "lineWidth": 2, "showPoints": "never", "spanNulls": True,
                           "stacking": {"mode": "normal" if stack else "none", "group": "A"}},
                "color": {"mode": "palette-classic"}}
    if decimals is not None:
        defaults["decimals"] = decimals
    if max_ is not None:
        defaults["max"] = max_
    return {
        "type": "timeseries", "title": title, "description": description, "w": w, "h": h,
        "targets": [_target(e, legend=l, ref=chr(65 + i)) for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": defaults, "overrides": overrides},
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def table(title, expr, description, columns, w=24, h=7, no_value="Nothing to show", sort=None, value_text=None):
    """Instant-query table showing only `columns` ({label: header}), plus the value if 'Value' is listed.
    value_text: {header: {raw value: (shown text, colour or None)}} to translate cell values."""
    overrides = [{"matcher": {"id": "byName", "options": header},
                  "properties": [{"id": "mappings", "value": [{"type": "value", "options": {
                      raw: ({"text": txt, "color": c} if c else {"text": txt}) for raw, (txt, c) in m.items()}}]},
                                 {"id": "custom.cellOptions", "value": {"type": "color-text"}}]}
                 for header, m in (value_text or {}).items()]
    return {
        "type": "table", "title": title, "description": description, "w": w, "h": h,
        "targets": [_target(expr, instant=True, fmt="table")],
        "fieldConfig": {"defaults": {"noValue": no_value, "custom": {"align": "left"}}, "overrides": overrides},
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                    "sortBy": [{"displayName": sort, "desc": True}] if sort else []},
        "transformations": [
            {"id": "filterFieldsByName", "options": {"include": {"names": list(columns)}}},
            {"id": "organize", "options": {"renameByName": columns,
                                           "indexByName": {k: i for i, k in enumerate(columns)}}},
        ],
    }


def logs(title, expr, description, w=24, h=12):
    return {
        "type": "logs", "title": title, "description": description, "w": w, "h": h, "datasource": LOKI,
        "targets": [{"datasource": LOKI, "expr": expr, "refId": "A", "queryType": "range"}],
        "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                    "enableLogDetails": True, "dedupStrategy": "none", "prettifyLogMessage": False},
    }


def dashboard(uid, title, description, panels, tags, variables=(), time_from="now-24h", refresh="1m"):
    """Lay panels out left-to-right, wrapping at 24 columns; rows and text always start a new line."""
    x = y = line_h = 0
    out = []
    for i, p in enumerate(panels, start=1):
        w, h = p.pop("w", 24), p.pop("h")
        if p["type"] in ("row", "text") or x + w > 24:
            x, y, line_h = 0, y + line_h, 0
        p["gridPos"] = {"x": x, "y": y, "w": w, "h": h}
        p["id"] = i
        p.setdefault("datasource", PROM)
        x += w
        line_h = max(line_h, h)
        if p["type"] in ("row", "text"):
            x, y, line_h = 0, y + h, 0
        out.append(p)
    return {
        "uid": uid, "title": title, "description": description, "tags": tags,
        "editable": True, "graphTooltip": 1, "schemaVersion": 39, "version": 1,
        "time": {"from": time_from, "to": "now"}, "refresh": refresh,
        "timepicker": {}, "timezone": "browser", "fiscalYearStartMonth": 0, "liveNow": False,
        "annotations": {"list": []}, "links": [
            {"title": "ShipZen dashboards", "type": "dashboards", "tags": ["shipzen"], "asDropdown": True,
             "includeVars": False, "keepTime": True, "icon": "external link"}],
        "templating": {"list": list(variables)},
        "panels": out,
    }


# ── 1. Overview: is everything OK? ───────────────────────────────────────────

def ready(ns, kind, name):
    metric = "kube_deployment_status_replicas_available" if kind == "deployment" else "kube_statefulset_status_replicas_ready"
    return f'(sum({metric}{{namespace="{ns}",{kind}=~"{name}"}}) or vector(0)) > bool 0'


tenant_apps_online = (f'count((sum by (namespace) (kube_deployment_status_replicas_available) > 0) '
                      f'and on (namespace) {TENANTS}) or vector(0)')
tenant_apps_unhealthy = (
    f'count((sum by (namespace) (kube_deployment_spec_replicas) - sum by (namespace) (kube_deployment_status_replicas_available) > 0) '
    f'and on (namespace) {TENANTS}) or vector(0)')
tenant_crashes_24h = (f'round(sum(increase(kube_pod_container_status_restarts_total[24h]) '
                      f'and on (namespace) {TENANTS})) or vector(0)')
tenant_requests_24h = (f'round(sum({by_app("increase(envoy_cluster_upstream_rq_total[24h])")} '
                       f'and on (namespace) {TENANTS})) or vector(0)')

PROBLEMS = 'ALERTS{alertstate="firing", severity!~"none|info"}'

# Alert names are identifiers; translate the ones that can fire here into plain words.
# Ours come from infra/system/shipzen-alerts.yaml, the rest from kube-prometheus-stack's defaults.
PROBLEM_TEXT = {
    "ShipZenServiceDown": "A ShipZen service is down",
    "GatewayDown": "Websites are unreachable (gateway down)",
    "DeployQueueDown": "The deploy queue is down",
    "DatabaseUnreachable": "The database cannot be reached",
    "AppOffline": "An app is offline",
    "AppKeepsCrashing": "An app keeps crashing",
    "AppErrorsHigh": "An app is returning many errors",
    "DeploysStuckInQueue": "Deploys are stuck waiting",
    "DeploysGaveUp": "Some deploys failed for good",
    "ServersAlmostFull": "Servers are almost full",
    "KubePodCrashLooping": "A program keeps crashing",
    "KubePodNotReady": "A program is not starting",
    "KubeDeploymentReplicasMismatch": "A service is not fully running",
    "KubeDeploymentRolloutStuck": "An update is stuck",
    "KubeStatefulSetReplicasMismatch": "A storage service is not fully running",
    "KubeJobFailed": "A background job failed",
    "KubePersistentVolumeFillingUp": "A storage disk is filling up",
    "NodeFilesystemSpaceFillingUp": "A server disk is filling up",
    "NodeFilesystemAlmostOutOfSpace": "A server disk is almost full",
    "KubeCPUOvercommit": "Not enough spare processing power",
    "KubeMemoryOvercommit": "Not enough spare memory",
    "KubeNodeNotReady": "A server is not responding",
    "TargetDown": "Monitoring cannot reach something",
    "PrometheusOperatorRejectedResources": "A monitoring setting was rejected",
}
SEVERITY_TEXT = {"critical": ("Urgent", RED), "high": ("High", RED), "warning": ("Should be checked", ORANGE)}

overview = dashboard(
    "shipzen-overview", "ShipZen — Overview",
    "Is ShipZen working right now? Start here.",
    tags=["shipzen"],
    panels=[
        text("### Is ShipZen working?\n"
             "Green means fine, **red means something needs attention**. Hover the **(i)** on any box for what it means. "
             "To look at one app, open **ShipZen — Your app** from the *ShipZen dashboards* menu at the top right.", h=3),
        row("Platform services"),
        status("Website", ready("shipzen-system", "deployment", "shipzen-ui"),
               "The ShipZen site people log in to. Down means nobody can open the dashboard."),
        status("API", ready("shipzen-system", "deployment", "shipzen-api"),
               "The service behind the website that handles every click (create project, deploy, etc.)."),
        status("Database", "max(shipzen_database_up)",
               "Where projects, users and deploy history are stored. If this is down, almost nothing works."),
        status("Deploy queue", ready("shipzen-system", "statefulset", "redis-master"),
               "Holds deploy requests until a builder picks them up. If down, new deploys wait."),
        status("Builders", ready("shipzen-system", "deployment", "shipzen-worker"),
               "Turn your code into a runnable app. If down, deploys stay queued until they come back."),
        status("App manager", ready("shipzen-system", "deployment", "shipzen-controller"),
               "Starts, updates and repairs running apps. If down, running apps keep working but nothing changes."),
        status("Internet gateway", ready("envoy-gateway-system", "deployment", "envoy-shipzen-system-.*"),
               "Sends visitors to the right app. If down, every site (including ShipZen itself) is unreachable."),
        status("Logs", ready("shipzen-system", "statefulset", "loki-stack"),
               "Collects app logs for the 'Your app' page. If down, apps still run; you just can't read new logs."),

        row("Problems right now"),
        stat("Open problems", f'count({PROBLEMS}) or vector(0)',
             "Automatic checks that are failing right now. 0 is what you want.",
             steps=((None, GREEN), (1, RED)), w=4, h=6),
        table("What's wrong", PROBLEMS,
              "Each row is a check that is failing. 'Where' is the app or area it concerns. "
              "Empty means nothing is wrong.",
              {"alertname": "Problem", "severity": "How serious", "namespace": "Where"},
              w=20, h=6, no_value="Nothing is wrong right now",
              value_text={"Problem": {k: (v, None) for k, v in PROBLEM_TEXT.items()}, "How serious": SEVERITY_TEXT}),

        row("Apps (last 24 hours)"),
        stat("Apps online", tenant_apps_online, "User apps with at least one copy running and answering.",
             steps=((None, GREEN),), w=6),
        stat("Apps with a problem", tenant_apps_unhealthy,
             "Apps that should be running but are not fully up (starting, crashing, or out of room).",
             steps=((None, GREEN), (1, RED)), w=6),
        stat("App crashes", tenant_crashes_24h,
             "How many times any app crashed and was restarted automatically. A few is normal; dozens is not.",
             steps=((None, GREEN), (5, ORANGE), (20, RED)), w=6),
        stat("Visitor requests", tenant_requests_24h,
             "Every page, image or API call that reached a user app through the internet gateway.",
             unit="short", w=6),

        row("Deploys (last 24 hours)"),
        stat("Deploys succeeded", 'round(sum(increase(shipzen_deployment_success_total[24h]))) or vector(0)',
             "Deploys that finished and went live.", steps=((None, GREEN),), w=4),
        stat("Deploys failed", 'round(sum(increase(shipzen_deployment_failure_total[24h]))) or vector(0)',
             "Deploys that did not go live (usually a build error in the app's code). Check that app's build log.",
             steps=((None, GREEN), (1, ORANGE)), w=4),
        stat("Building now", 'max(shipzen_messages_in_flight) or vector(0)',
             "Deploys a builder is working on at this moment.", w=4),
        stat("Waiting in line", 'max(shipzen_queue_depth) or vector(0)',
             "Deploys waiting for a free builder. Should normally be 0.",
             steps=((None, GREEN), (5, ORANGE), (20, RED)), w=4),
        stat("Gave up after retries", 'max(shipzen_dlq_depth) or vector(0)',
             "Deploys that failed repeatedly and were set aside. Anything above 0 needs a person to look.",
             steps=((None, GREEN), (1, RED)), w=4),
        stat("Typical build time",
             'histogram_quantile(0.5, sum by (le) (increase(shipzen_build_duration_seconds_bucket[24h]))) '
             'and on () sum(increase(shipzen_build_duration_seconds_count[24h])) > 0',
             "Half of builds finished faster than this.", unit="s", no_value="No builds", w=4),

        row("Room to grow"),
        gauge("Server capacity booked (CPU)",
              'sum(kube_pod_container_resource_requests{resource="cpu"} and on (namespace, pod) (kube_pod_status_phase{phase=~"Pending|Running"} == 1)) '
              '/ sum(kube_node_status_allocatable{resource="cpu"})',
              "Share of processing power already promised to running apps. New apps cannot start once this is full."),
        gauge("Server capacity booked (memory)",
              'sum(kube_pod_container_resource_requests{resource="memory"} and on (namespace, pod) (kube_pod_status_phase{phase=~"Pending|Running"} == 1)) '
              '/ sum(kube_node_status_allocatable{resource="memory"})',
              "Share of memory already promised to running apps. New apps cannot start once this is full."),
        gauge("Processing power actually in use",
              'sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) '
              '/ sum(kube_node_status_allocatable{resource="cpu"})',
              "How busy the servers really are right now. Usually much lower than what is booked."),
        stat("Servers", 'count(kube_node_info)', "Machines everything runs on.", w=6, h=6),
    ],
)


# ── 2. One app ───────────────────────────────────────────────────────────────

APP_VAR = {
    "name": "app", "label": "App", "type": "query", "datasource": PROM,
    "query": {"query": f'label_values({TENANTS}, namespace)', "refId": "app"},
    "definition": f'label_values({TENANTS}, namespace)', "refresh": 2, "sort": 1,
    "includeAll": False, "multi": False, "current": {}, "options": [], "hide": 0,
}
SEARCH_VAR = {"name": "search", "label": "Find in logs", "type": "textbox", "query": "", "current": {"text": "", "value": ""},
              "hide": 0, "description": "Only show log lines containing this text (case-sensitive). Leave empty for all."}

APP_RQ = 'envoy_cluster_upstream_rq_total{envoy_cluster_name=~"httproute/$app/.*"}'
APP_RQ_TIME = 'envoy_cluster_upstream_rq_time_bucket{envoy_cluster_name=~"httproute/$app/.*"}'
APP_RQ_COUNT = 'envoy_cluster_upstream_rq_time_count{envoy_cluster_name=~"httproute/$app/.*"}'


def app_rq_xx(code_class: str) -> str:
    """Requests to $app whose status class (2,3,4,5) matches the regex."""
    return f'envoy_cluster_upstream_rq_xx{{envoy_cluster_name=~"httproute/$app/.*",envoy_response_code_class=~"{code_class}"}}'


def guard(expr: str, denominator: str) -> str:
    """Return nothing (shown as the panel's 'no value' text) instead of NaN when there is no data."""
    return f'({expr}) and on () ({denominator}) > 0'


VISITS = f'sum(increase({APP_RQ}[$__range]))'
VISITS_TIMED = f'sum(increase({APP_RQ_COUNT}[$__range]))'
BUILDS = 'sum(increase(shipzen_build_duration_seconds_count[$__range]))'
FINISHED = ('(sum(increase(shipzen_deployment_success_total[$__range])) + '
            'sum(increase(shipzen_deployment_failure_total[$__range])))')
QUEUED = 'sum(increase(shipzen_queue_latency_seconds_count[$__range]))'

app = dashboard(
    "shipzen-app", "ShipZen — Your app",
    "Health, traffic and logs for one app. Pick the app at the top.",
    tags=["shipzen"], variables=[APP_VAR, SEARCH_VAR],
    panels=[
        text("### How is this app doing?\n"
             "Pick the app in the **App** box at the top. Numbers cover the time range at the top right "
             "(last 24 hours unless you change it).", h=3),
        stat("Status", 'sum(kube_deployment_status_replicas_available{namespace="$app"}) or vector(0)',
             "Online means at least one copy of the app is running and answering.",
             mappings=[{"type": "value", "options": {"0": {"text": "Offline", "color": RED, "index": 0}}},
                       {"type": "range", "options": {"from": 1, "to": 1000,
                                                    "result": {"text": "Online", "color": GREEN, "index": 1}}}],
             steps=((None, RED), (1, GREEN)), w=4),
        stat("Visitor requests", f'round(sum(increase({APP_RQ}[$__range]))) or vector(0)',
             "Pages, images and API calls served to visitors.", unit="short", w=4),
        stat("Failed requests",
             guard(f'(sum(increase({app_rq_xx("5")}[$__range])) or vector(0)) / {VISITS}', VISITS),
             "Share of visits where the app itself errored (a 5xx response). Under 1% is healthy.",
             unit="percentunit", decimals=1, steps=((None, GREEN), (0.01, ORANGE), (0.05, RED)),
             no_value="No visits", w=4),
        stat("Typical response time",
             guard(f'histogram_quantile(0.5, sum by (le) (increase({APP_RQ_TIME}[$__range])))', VISITS_TIMED),
             "Half of visits were answered faster than this.", unit="ms", no_value="No visits",
             steps=((None, GREEN), (500, ORANGE), (2000, RED)), w=4),
        stat("Slowest 5% took",
             guard(f'histogram_quantile(0.95, sum by (le) (increase({APP_RQ_TIME}[$__range])))', VISITS_TIMED),
             "The slowest 1 in 20 visits took at least this long.", unit="ms", no_value="No visits",
             steps=((None, GREEN), (1000, ORANGE), (5000, RED)), w=4),
        stat("Crashes", 'round(sum(increase(kube_pod_container_status_restarts_total{namespace="$app"}[$__range]))) or vector(0)',
             "Times the app crashed and was restarted automatically.",
             steps=((None, GREEN), (1, ORANGE), (5, RED)), w=4),

        graph("Visitors per minute",
              [(f'sum(rate({app_rq_xx("2|3")}[5m])) * 60', "OK"),
               (f'sum(rate({app_rq_xx("4")}[5m])) * 60', "Not found / not allowed"),
               (f'sum(rate({app_rq_xx("5")}[5m])) * 60', "App error")],
              "Requests per minute, split by outcome. 'App error' should stay near zero.",
              unit="short", stack=True, colors={"OK": GREEN, "Not found / not allowed": ORANGE, "App error": RED}),
        graph("Response time",
              [(f'histogram_quantile(0.5, sum by (le) (rate({APP_RQ_TIME}[5m])))', "Typical visit"),
               (f'histogram_quantile(0.95, sum by (le) (rate({APP_RQ_TIME}[5m])))', "Slowest 5%")],
              "How long visitors wait for an answer.", unit="ms"),
        graph("How hard the app is working",
              [('sum(rate(container_cpu_usage_seconds_total{namespace="$app", container!="", container!="POD"}[5m])) '
                '/ sum(kube_pod_container_resource_limits{namespace="$app", resource="cpu"})', "Processing power"),
               ('sum(container_memory_working_set_bytes{namespace="$app", container!="", container!="POD"}) '
                '/ sum(kube_pod_container_resource_limits{namespace="$app", resource="memory"})', "Memory")],
              "Share of the app's allowance in use. Near 100% memory means the app will be restarted; "
              "near 100% processing power means it slows down.", unit="percentunit", max_=1),
        graph("Crashes",
              [('round(sum(increase(kube_pod_container_status_restarts_total{namespace="$app"}[10m])))', "Restarts")],
              "Each bar is a crash followed by an automatic restart. Read the logs below around that time.",
              bars=True, colors={"Restarts": RED}, decimals=0),
        logs("App logs", '{namespace="$app"} |= "$search"',
             "What the app printed, newest first. Type in 'Find in logs' at the top to filter."),
    ],
)


# ── 3. Deploys & builds ──────────────────────────────────────────────────────

deploys = dashboard(
    "shipzen-deploys", "ShipZen — Deploys & builds",
    "Are deploys going through, and how long do they take?",
    tags=["shipzen"], time_from="now-7d", refresh="5m",
    panels=[
        text("### Deploys and builds\n"
             "Every deploy builds the app from its code, then starts it. Numbers cover the time range at the top right.", h=2),
        stat("Succeeded", 'round(sum(increase(shipzen_deployment_success_total[$__range]))) or vector(0)',
             "Deploys that went live.", steps=((None, GREEN),)),
        stat("Failed", 'round(sum(increase(shipzen_deployment_failure_total[$__range]))) or vector(0)',
             "Deploys that did not go live. Usually a problem in the app's own code; see its build log in ShipZen.",
             steps=((None, GREEN), (1, ORANGE))),
        stat("Success rate",
             guard('sum(increase(shipzen_deployment_success_total[$__range])) / ' + FINISHED, FINISHED),
             "Share of finished deploys that went live.", unit="percentunit", decimals=0,
             steps=((None, RED), (0.7, ORANGE), (0.9, GREEN)), no_value="No deploys"),
        stat("Typical build time", guard('histogram_quantile(0.5, sum by (le) (increase(shipzen_build_duration_seconds_bucket[$__range])))', BUILDS),
             "Half of builds finished faster than this.", unit="s", no_value="No builds"),
        stat("Slowest builds", guard('histogram_quantile(0.95, sum by (le) (increase(shipzen_build_duration_seconds_bucket[$__range])))', BUILDS),
             "1 in 20 builds took at least this long.", unit="s", no_value="No builds",
             steps=((None, GREEN), (600, ORANGE), (1200, RED))),
        stat("Typical wait before building", guard('histogram_quantile(0.5, sum by (le) (increase(shipzen_queue_latency_seconds_bucket[$__range])))', QUEUED),
             "How long a deploy usually waits for a free builder.", unit="s", no_value="No deploys",
             steps=((None, GREEN), (60, ORANGE), (300, RED))),

        graph("Deploys per hour",
              [('round(sum(increase(shipzen_deployment_success_total[1h])))', "Succeeded"),
               ('round(sum(increase(shipzen_deployment_failure_total[1h])))', "Failed")],
              "Finished deploys each hour.", bars=True, stack=True, decimals=0,
              colors={"Succeeded": GREEN, "Failed": RED}),
        graph("Build time",
              [('histogram_quantile(0.5, sum by (le) (rate(shipzen_build_duration_seconds_bucket[1h])))', "Typical"),
               ('histogram_quantile(0.95, sum by (le) (rate(shipzen_build_duration_seconds_bucket[1h])))', "Slowest 5%")],
              "How long builds take. Big jumps usually mean a heavier app or busy servers.", unit="s"),
        graph("Deploy line",
              [('max(shipzen_queue_depth)', "Waiting"),
               ('max(shipzen_messages_in_flight)', "Building"),
               ('max(shipzen_dlq_depth)', "Gave up")],
              "'Waiting' should drain quickly. 'Gave up' above 0 needs a person.",
              colors={"Waiting": ORANGE, "Building": BLUE, "Gave up": RED}, decimals=0),
        graph("Automatic retries per hour",
              [('round(sum(increase(shipzen_retry_total[1h])))', "Retries")],
              "Deploys that hit a temporary error and were tried again. Occasional retries are normal.",
              bars=True, decimals=0, colors={"Retries": ORANGE}),
    ],
)


GW_5XX = 'rate(envoy_cluster_upstream_rq_xx{envoy_response_code_class="5"}[5m])'

# ── 4. Technical (operators only) ────────────────────────────────────────────

internals = dashboard(
    "shipzen-internals", "ShipZen — Platform internals",
    "Operator view: API golden signals, gateway, controller, queue, cluster resources, scrape health.",
    tags=["shipzen", "technical"], time_from="now-6h", refresh="1m",
    panels=[
        row("API"),
        graph("Requests/s by route", [('sum by (route) (rate(shipzen_api_requests_total{route!="/healthz"}[5m]))', "{{route}}")],
              "Excludes /healthz probes.", unit="reqps", w=8),
        graph("5xx ratio by route",
              [('sum by (route) (rate(shipzen_api_requests_total{status=~"5.."}[5m])) / sum by (route) (rate(shipzen_api_requests_total[5m]))', "{{route}}")],
              "Server errors as a share of requests.", unit="percentunit", w=8),
        graph("p95 latency by route",
              [('histogram_quantile(0.95, sum by (le, route) (rate(shipzen_api_request_duration_seconds_bucket{route!="/healthz"}[5m])))', "{{route}}")],
              "", unit="s", w=8),
        row("Gateway (Envoy)"),
        graph("Requests/s by namespace", [(f'sum by (namespace) ({by_app("rate(envoy_cluster_upstream_rq_total[5m])")})', "{{namespace}}")],
              "All HTTPRoutes, including ShipZen, ArgoCD and Grafana.", unit="reqps", w=12),
        graph("5xx/s by namespace",
              [(f'sum by (namespace) ({by_app(GW_5XX)})', "{{namespace}}")],
              "", unit="reqps", w=12),
        row("Controller and queue"),
        graph("Reconcile duration (avg)",
              [('sum(rate(shipzen_reconciliation_duration_seconds_sum[5m])) / sum(rate(shipzen_reconciliation_duration_seconds_count[5m]))', "avg")],
              "Leader's full sweep time. Should stay well under the 15 s interval.", unit="s", w=8),
        graph("Drift corrections/h", [('sum(increase(shipzen_drift_total[1h]))', "drift")],
              "Missing or orphaned objects the controller repaired. Sustained > 0 means something keeps undoing it.", w=8, decimals=0),
        graph("Queue latency p95", [('histogram_quantile(0.95, sum by (le) (rate(shipzen_queue_latency_seconds_bucket[15m])))', "p95")],
              "Enqueue → worker pickup.", unit="s", w=8),
        row("Cluster"),
        graph("CPU by namespace", [('sum by (namespace) (rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m]))', "{{namespace}}")],
              "", unit="cores", w=8, stack=True),
        graph("Memory by namespace", [('sum by (namespace) (container_memory_working_set_bytes{container!="", container!="POD"})', "{{namespace}}")],
              "", unit="bytes", w=8, stack=True),
        graph("Node CPU / memory used",
              [('1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))', "cpu {{instance}}"),
               ('1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes', "mem {{instance}}")],
              "", unit="percentunit", w=8, max_=1),
        table("Restarts in the last 24h",
              'sort_desc(round(sum by (namespace, pod) (increase(kube_pod_container_status_restarts_total[24h]))) > 0)',
              "Pods that restarted.", {"namespace": "Namespace", "pod": "Pod", "Value": "Restarts"},
              w=12, h=8, no_value="No restarts", sort="Restarts"),
        table("Disks", 'kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes',
              "Persistent volume usage.", {"namespace": "Namespace", "persistentvolumeclaim": "Volume", "Value": "Used"},
              w=12, h=8, no_value="No volumes", sort="Used"),
        table("Scrape targets down", 'up == 0', "Prometheus targets that are not answering.",
              {"job": "Job", "namespace": "Namespace", "instance": "Instance"}, w=24, h=5, no_value="All targets up"),
    ],
)
# Show 'Used' on the disks table as a percentage.
for p in internals["panels"]:
    if p.get("title") == "Disks":
        p["fieldConfig"]["overrides"] = [{"matcher": {"id": "byName", "options": "Used"},
                                          "properties": [{"id": "unit", "value": "percentunit"},
                                                         {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic"}},
                                                         {"id": "max", "value": 1}, {"id": "min", "value": 0},
                                                         {"id": "thresholds", "value": _thresholds([(None, GREEN), (0.8, ORANGE), (0.9, RED)])}]}]


FOLDERS = {
    "ShipZen": {"shipzen-overview.json": overview, "shipzen-app.json": app, "shipzen-deploys.json": deploys},
    "ShipZen (technical)": {"shipzen-internals.json": internals},
}


def render() -> str:
    docs = ["# GENERATED by observability/dashboards.py. Do not edit by hand: edit that file and re-run it.\n"]
    for folder, files in FOLDERS.items():
        slug = "grafana-dashboards-" + ("technical" if "technical" in folder else "shipzen")
        body = [f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {slug}\n  namespace: observability\n"
                f"  labels:\n    grafana_dashboard: \"1\"\n  annotations:\n    grafana_folder: \"{folder}\"\ndata:\n"]
        for name, dash in files.items():
            js = json.dumps(dash, indent=2, ensure_ascii=False)
            body.append(f"  {name}: |-\n" + "\n".join("    " + line for line in js.splitlines()) + "\n")
        docs.append("".join(body))
    return "---\n".join(docs)


if __name__ == "__main__":
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT)}")
