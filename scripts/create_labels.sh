#!/usr/bin/env bash
# Bulk-create GitHub labels for the blackstar-discord-bot repository.
# Usage: bash scripts/create_labels.sh
set -euo pipefail

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

declare -A LABELS=(
  ["bug"]="d73a4a:Confirmed defect in existing functionality"
  ["audio-quality"]="e4a817:Issues affecting the guitar tone or stream quality"
  ["latency"]="e4a817:Timing / buffer / jitter issues"
  ["enhancement"]="a2eeef:New feature or improvement request"
  ["device-compat"]="0075ca:USB audio device / macOS Core Audio compatibility"
  ["ci"]="0075ca:GitHub Actions / pre-commit infrastructure"
  ["dependencies"]="0075ca:Dependency upgrades"
  ["documentation"]="0075ca:README inline docs PLAN.md"
  ["good first issue"]="7057ff:Suitable for a first contribution"
  ["help wanted"]="008672:Extra attention needed"
  ["duplicate"]="cfd3d7:Already reported"
  ["wontfix"]="ffffff:Out of scope"
  ["agent:audio"]="f9d0c4:Work owned by the Audio Agent"
  ["agent:bot"]="f9d0c4:Work owned by the Bot Agent"
  ["agent:infra"]="f9d0c4:Work owned by the Infra Agent"
  ["agent:qa"]="f9d0c4:Work owned by the QA Agent"
)

for name in "${!LABELS[@]}"; do
  IFS=":" read -r color description <<< "${LABELS[$name]}"
  gh label create "$name" --color "$color" --description "$description" \
    --repo "$REPO" --force
done

echo "Labels created successfully."
