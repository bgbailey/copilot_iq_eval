#!/usr/bin/env bash
# =============================================================================================
# Spike S3: can the Agent Evaluations CLI run headless as each persona, and what does its JSON
# report contain? (ADR-003; config/contracts.yaml `agent_evaluations_cli`)
#
#   spikes/s3_cli_probe.sh --persona exec --agent-id <M365_AGENT_ID>
#
# Writes a two-prompt dataset (REV-001 and JNT-001), runs the CLI once and records, under
# spikes/out/s3/<persona>-<time>/: the dataset, the report, stdout/stderr, the exit code and
# duration, and which files the CLI created in your home folder (its token cache: can a cache
# per persona be swapped in for headless runs?).
#
# It runs `npx -y @microsoft/m365-copilot-eval` (Microsoft's package on npm), which signs in
# interactively the first time: sign in as the persona's UPN.
# Needs Node.js 18 or later and, in the environment or config/settings.toml:
#   TENANT_ID, AZURE_AI_PROJECT_ENDPOINT, AZURE_AI_MODEL_NAME (the judge deployment).
# =============================================================================================
set -euo pipefail

persona="exec"
agent_id="${M365_AGENT_ID:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --persona)  persona="$2"; shift 2 ;;
    --agent-id) agent_id="$2"; shift 2 ;;
    -h|--help)  sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
: "${TENANT_ID:?set TENANT_ID}" "${AZURE_AI_PROJECT_ENDPOINT:?set AZURE_AI_PROJECT_ENDPOINT}"
: "${AZURE_AI_MODEL_NAME:=gpt-5-mini}"
[[ -n "$agent_id" ]] || { echo "pass --agent-id or set M365_AGENT_ID (the declarative agent, P4.1)" >&2; exit 2; }
export TENANT_ID AZURE_AI_PROJECT_ENDPOINT AZURE_AI_MODEL_NAME M365_AGENT_ID="$agent_id"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="${root}/spikes/out/s3/${persona}-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$out"

# Dataset schema 1.6.0 (S12). The top-level shape is part of what this spike confirms.
cat > "${out}/dataset.json" <<'JSON'
{
  "schemaVersion": "1.6.0",
  "items": [
    {"testId": "REV-001", "category": "single-model", "prompt": "What was gross revenue in FY2025?",
     "expected_response": "FY2025 gross revenue from the certified Sales Analytics model.",
     "evaluators": ["Citations"], "evaluators_mode": "extend"},
    {"testId": "JNT-001", "category": "joint", "prompt": "Did we hit our FY2025 gross revenue target?",
     "expected_response": "Actual from Sales Analytics compared with the approved target in FY2025 Revenue Targets - APPROVED.",
     "evaluators": ["Citations"], "evaluators_mode": "extend"}
  ]
}
JSON

marker="$(mktemp)"
started=$(date +%s)
set +e
npx -y @microsoft/m365-copilot-eval runevals --prompts-file "${out}/dataset.json" --output "${out}/report.json" \
  >"${out}/stdout.txt" 2>"${out}/stderr.txt"
exit_code=$?
set -e
elapsed=$(( $(date +%s) - started ))
find "$HOME" -maxdepth 3 -newer "$marker" -type f -not -path "*/node_modules/*" -not -path "*/.npm/*" \
  2>/dev/null > "${out}/new-files.txt" || true
rm -f "$marker"

echo "S3 ${persona}: exit ${exit_code} after ${elapsed} s"
echo "Report: ${out}/report.json"
echo "Files the CLI created under \$HOME (token cache candidates):"
sed 's/^/  /' "${out}/new-files.txt"
echo "For ADR-003: does report.json hold the answer text, citations (Power BI URLs?) and timestamps?"
