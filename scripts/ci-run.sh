#!/usr/bin/env bash
# Run a CI command; if it fails, publish the tail of its output as a GitHub
# error annotation.
#
# Why: annotations are readable through the plain GitHub API (and show on the
# run summary page), while full job logs require a separate download. This
# makes the reason for a failure visible without opening the raw log.
#
# Usage: bash scripts/ci-run.sh "<label>" <command> [args...]
set -o pipefail
label="$1"; shift
log="$(mktemp)"

"$@" 2>&1 | tee "$log"
status=${PIPESTATUS[0]}

if [ "$status" -ne 0 ]; then
  # Strip ANSI colours, keep the last 60 lines, escape for the annotation format.
  tail_text="$(sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' "$log" | tail -n 60)"
  tail_text="${tail_text//'%'/'%25'}"
  tail_text="${tail_text//$'\r'/'%0D'}"
  tail_text="${tail_text//$'\n'/'%0A'}"
  echo "::error title=${label} failed (exit ${status})::${tail_text}"
fi
rm -f "$log"
exit "$status"
