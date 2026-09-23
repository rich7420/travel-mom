#!/usr/bin/env bash
# Read-only preflight for the machine that hosts OpenClaw + Mom Travel Desk.
# It intentionally does not print environment variables or edit configuration.
set -uo pipefail

TRAVEL_DESK_URL="${TRAVEL_DESK_URL:-http://127.0.0.1:8000}"
OPENCLAW_BROWSER_PROFILE="${OPENCLAW_BROWSER_PROFILE:-openclaw}"
FAILURES=0
WARNINGS=0

section() {
  printf '\n\033[1m== %s ==\033[0m\n' "$1"
}

run_required() {
  local label="$1"; shift
  section "$label"
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
  if "$@"; then
    printf '[PASS] %s\n' "$label"
  else
    local rc=$?
    printf '[FAIL] %s (exit=%s)\n' "$label" "$rc" >&2
    FAILURES=$((FAILURES + 1))
  fi
}

run_optional() {
  local label="$1"; shift
  section "$label"
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
  if "$@"; then
    printf '[PASS] %s\n' "$label"
  else
    local rc=$?
    printf '[WARN] %s (exit=%s); this optional check may need its plugin/artifact enabled.\n' "$label" "$rc" >&2
    WARNINGS=$((WARNINGS + 1))
  fi
}

if ! command -v openclaw >/dev/null 2>&1; then
  echo '[FAIL] openclaw is not on PATH.' >&2
  exit 127
fi

run_required 'OpenClaw version' openclaw --version
run_required 'Configuration schema validation' openclaw config validate --json
run_required 'Read-only doctor lint' openclaw doctor --lint --json
run_required 'Gateway security audit' openclaw security audit --json
run_required 'Gateway runtime status' openclaw gateway status --deep
run_required 'Managed browser readiness' openclaw browser --browser-profile "${OPENCLAW_BROWSER_PROFILE}" doctor --deep
run_optional 'Workspace policy conformance' openclaw policy check --json

if command -v curl >/dev/null 2>&1; then
  run_required 'Travel Desk health' curl -fsS "${TRAVEL_DESK_URL}/health"
  run_required 'Travel Desk configuration readiness' curl -fsS "${TRAVEL_DESK_URL}/api/system/readiness"
else
  echo '[WARN] curl is unavailable; skipped Travel Desk HTTP checks.' >&2
  WARNINGS=$((WARNINGS + 1))
fi

section 'Summary'
printf 'failures=%s warnings=%s\n' "$FAILURES" "$WARNINGS"
if (( FAILURES > 0 )); then
  exit 1
fi
exit 0
