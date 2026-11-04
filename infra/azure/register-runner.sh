#!/usr/bin/env bash
# =============================================================================================
# Register the runner VM with GitHub as a self-hosted runner (docs/deployment.md, P9.2).
#
#   infra/azure/register-runner.sh --resource-group RG --vm VM_NAME --repo OWNER/REPO [--labels L]
#
# Runs entirely from your machine: no SSH, no inbound port. It
#   1. asks GitHub for a short-lived registration token (gh, with admin rights on the repo);
#   2. looks up the latest runner release and its published SHA-256 digest;
#   3. uses `az vm run-command` to download the runner on the VM, verify the digest, register it
#      as the `runner` user and install it as a service.
# The token expires after an hour and only registers runners; it is passed to the VM as a
# run-command argument, not stored in the repository or the template.
# =============================================================================================
set -euo pipefail

resource_group=""
vm=""
repo=""
labels="self-hosted,linux,copilot-evals"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group|-g) resource_group="$2"; shift 2 ;;
    --vm)                vm="$2"; shift 2 ;;
    --repo)              repo="$2"; shift 2 ;;
    --labels)            labels="$2"; shift 2 ;;
    -h|--help)           sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$resource_group" && -n "$vm" && -n "$repo" ]] || { echo "--resource-group, --vm and --repo are required" >&2; exit 2; }

release="$(gh api repos/actions/runner/releases/latest)"
version="$(jq -r '.tag_name' <<<"$release" | sed 's/^v//')"
asset="actions-runner-linux-x64-${version}.tar.gz"
sha256="$(jq -r --arg name "$asset" '.assets[] | select(.name == $name) | .digest // empty' <<<"$release" | sed 's/^sha256://')"
[[ -n "$sha256" ]] || { echo "GitHub published no SHA-256 digest for ${asset}; not installing an unverified runner" >&2; exit 1; }
token="$(gh api -X POST "repos/${repo}/actions/runners/registration-token" --jq .token)"

# Runs on the VM as root. Arguments: version asset sha256 repo token labels.
read -r -d '' install <<'SCRIPT' || true
set -euo pipefail
version="$1"; asset="$2"; sha256="$3"; repo="$4"; token="$5"; labels="$6"
cd /opt/actions-runner
curl -fsSL -o runner.tar.gz "https://github.com/actions/runner/releases/download/v${version}/${asset}"
echo "${sha256}  runner.tar.gz" | sha256sum --check --strict -
tar xzf runner.tar.gz && rm runner.tar.gz
./bin/installdependencies.sh
chown -R runner:runner /opt/actions-runner
sudo -u runner ./config.sh --unattended --replace --url "https://github.com/${repo}" --token "${token}" \
  --labels "${labels}" --name "$(hostname)"
./svc.sh install runner
./svc.sh start
SCRIPT

echo "Installing runner ${version} on ${vm} (labels: ${labels}) ..."
az vm run-command invoke --resource-group "$resource_group" --name "$vm" --command-id RunShellScript \
  --scripts "$install" --parameters "$version" "$asset" "$sha256" "$repo" "$token" "$labels" \
  --query 'value[0].message' --output tsv
echo "Done. Check Settings > Actions > Runners in ${repo}; workflows select it with runs-on: [self-hosted, copilot-evals]."
