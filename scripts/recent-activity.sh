#!/usr/bin/env bash
# Is someone working on ShipZen right now?
#
#   bash scripts/recent-activity.sh PROJECT_ID OWNER/REPO MINUTES
#
# Exit 0 (and print why) if there was human activity in the last MINUTES,
# exit 1 if the platform looks idle. Used by Auto-Destroy to postpone teardown
# during a session. Needs GH_TOKEN for the GitHub checks.
#
# What counts as activity:
#   1. Successful requests to the ShipZen API (using the UI or API). Health
#      checks, /metrics, webhooks and failed requests (internet scanners get
#      404/401) are ignored.
#   2. kubectl/API writes to the cluster by a person (not a service account).
#   3. Pushes to the repo or workflows started by a person (not by a bot or by
#      Auto-Destroy itself).
set -uo pipefail

P="${1:?usage: recent-activity.sh PROJECT_ID OWNER/REPO MINUTES}"
REPO="${2:?usage: recent-activity.sh PROJECT_ID OWNER/REPO MINUTES}"
MIN="${3:?usage: recent-activity.sh PROJECT_ID OWNER/REPO MINUTES}"
SINCE=$(date -u -d "-${MIN} minutes" +%Y-%m-%dT%H:%M:%SZ)
active=1

count_logs() {
  gcloud logging read "timestamp>=\"$SINCE\" AND $1" --project "$P" \
    --limit 50 --format='value(timestamp)' 2>/dev/null | grep -c . || true
}

api=$(count_logs 'resource.type="k8s_container" AND resource.labels.namespace_name="shipzen-system" AND resource.labels.container_name="api" AND textPayload=~"HTTP/1.1\" [23][0-9][0-9] " AND NOT textPayload:"/healthz" AND NOT textPayload:"/metrics" AND NOT textPayload:"/webhooks/"')
if [ "${api:-0}" -gt 0 ]; then
  echo "ShipZen API: $api successful request(s) in the last ${MIN} min"
  active=0
fi

kube=$(count_logs 'resource.type="k8s_cluster" AND logName:"cloudaudit.googleapis.com%2Factivity" AND protoPayload.authenticationInfo.principalEmail:"@" AND NOT protoPayload.authenticationInfo.principalEmail:"gserviceaccount.com"')
if [ "${kube:-0}" -gt 0 ]; then
  echo "kubectl: $kube change(s) by a person in the last ${MIN} min"
  active=0
fi

if [ -n "${GH_TOKEN:-}" ]; then
  pushes=$(gh api "repos/$REPO/events?per_page=100" --jq "[.[] | select(.created_at >= \"$SINCE\") | select(.type == \"PushEvent\" or .type == \"PullRequestEvent\" or .type == \"CreateEvent\") | select(.actor.login | test(\"\\\\[bot\\\\]$\") | not)] | length" 2>/dev/null || echo 0)
  if [ "${pushes:-0}" -gt 0 ]; then
    echo "GitHub: $pushes push/PR event(s) in the last ${MIN} min"
    active=0
  fi
  runs=$(gh api "repos/$REPO/actions/runs?created=>=$SINCE&per_page=100" --jq "[.workflow_runs[] | select(.name != \"Auto-Destroy (Deadman Switch)\" and .name != \"Infra Teardown\") | select(.triggering_actor.login | test(\"\\\\[bot\\\\]$\") | not)] | length" 2>/dev/null || echo 0)
  if [ "${runs:-0}" -gt 0 ]; then
    echo "GitHub: $runs workflow run(s) started by a person in the last ${MIN} min"
    active=0
  fi
fi

[ "$active" = 0 ] || echo "No activity in the last ${MIN} min"
exit "$active"
