#!/usr/bin/env bash
# Refresh ibm_iam_service_policy with IBM-Cloud/ibm 2.5.0 under three grants.
#
# 1. Caller has Viewer on IAM Access Management. Refresh should 403.
# 2. Add platform Viewer on one Container Registry namespace. Refresh again.
# 3. Remove that grant. Refresh should 403 again.
#
# Requires an administrator key in IBMCLOUD_API_KEY or IC_API_KEY.
# Terraform state and logs stay under ./out and the stack directories.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN_DIR="$ROOT/terraform/admin"
REFRESH_DIR="$ROOT/terraform/refresh"
OUT_DIR="$ROOT/out"
WAIT_SECONDS="${WAIT_SECONDS:-45}"
REGISTRY_NAMESPACE="${REGISTRY_NAMESPACE:-dreamvu-data-mover}"
REGISTRY_REGION="${REGISTRY_REGION:-jp-tok}"
CODEENGINE_REGION="${CODEENGINE_REGION:-jp-tok}"
CODEENGINE_PROJECT_ID="${CODEENGINE_PROJECT_ID:-353e8ce5-42e6-49b6-b1b2-b7f1feff343a}"
NAME_PREFIX="${NAME_PREFIX:-dreamvu-iam-repro}"

mkdir -p "$OUT_DIR"

admin_key="${IBMCLOUD_API_KEY:-${IC_API_KEY:-}}"
if [[ -z "$admin_key" ]]; then
  echo "Set IBMCLOUD_API_KEY to an administrator API key." >&2
  exit 1
fi

use_key() {
  local key="$1"
  export IC_API_KEY="$key"
  export IBMCLOUD_API_KEY="$key"
}

admin_apply() {
  local grant="$1"
  use_key "$admin_key"
  terraform -chdir="$ADMIN_DIR" apply -auto-approve -input=false \
    -var "grant_registry_viewer=${grant}" \
    -var "registry_namespace=${REGISTRY_NAMESPACE}" \
    -var "registry_region=${REGISTRY_REGION}" \
    -var "codeengine_region=${CODEENGINE_REGION}" \
    -var "codeengine_project_id=${CODEENGINE_PROJECT_ID}" \
    -var "name_prefix=${NAME_PREFIX}"
}

refresh_plan() {
  local phase="$1"
  local caller_key="$2"
  local log_file="$OUT_DIR/${phase}.log"

  use_key "$caller_key"
  echo
  echo "======== terraform phase ${phase} ========"
  set +e
  TF_LOG_PROVIDER=DEBUG terraform -chdir="$REFRESH_DIR" plan -refresh-only -input=false -no-color \
    -var "subject_service_id=${subject_service_id}" \
    -var "codeengine_region=${CODEENGINE_REGION}" \
    -var "codeengine_project_id=${CODEENGINE_PROJECT_ID}" \
    >"$log_file" 2>&1
  local code=$?
  set -e
  python3 - "$log_file" <<'PY'
import re
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(errors="replace")
text = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1<redacted>", text)
text = re.sub(r"(?i)(apikey(=|%3D|:)\s*)[^&\s\"']+", r"\1<redacted>", text)
path.write_text(text)
PY
  echo "provider log: $log_file (Authorization redacted)"
  if grep -n -E "v2/policies|Error retrieving servicePolicy|status code:|403|200" "$log_file" | head -n 40; then
    :
  fi
  echo "terraform exit ${code}"
  echo "$code" >"$OUT_DIR/${phase}.exit"
  return 0
}

cleanup() {
  use_key "$admin_key"
  terraform -chdir="$ADMIN_DIR" destroy -auto-approve -input=false \
    -var "grant_registry_viewer=false" \
    -var "registry_namespace=${REGISTRY_NAMESPACE}" \
    -var "registry_region=${REGISTRY_REGION}" \
    -var "codeengine_region=${CODEENGINE_REGION}" \
    -var "codeengine_project_id=${CODEENGINE_PROJECT_ID}" \
    -var "name_prefix=${NAME_PREFIX}"
  rm -rf "$REFRESH_DIR"/terraform.tfstate "$REFRESH_DIR"/terraform.tfstate.backup
}

if [[ "${1:-}" == "cleanup" ]]; then
  cleanup
  exit 0
fi

use_key "$admin_key"
terraform -chdir="$ADMIN_DIR" init -input=false
terraform -chdir="$REFRESH_DIR" init -input=false

admin_apply false

subject_service_id="$(terraform -chdir="$ADMIN_DIR" output -raw subject_service_id)"
policy_tf_id="$(terraform -chdir="$ADMIN_DIR" output -raw codeengine_policy_terraform_id)"
caller_key="$(terraform -chdir="$ADMIN_DIR" output -raw caller_api_key)"

echo "subject service id: ${subject_service_id}"
echo "codeengine project: ${CODEENGINE_REGION} / ${CODEENGINE_PROJECT_ID}"
echo "registry namespace: ${REGISTRY_REGION} / ${REGISTRY_NAMESPACE}"
echo "policy terraform id: ${policy_tf_id}"
echo "waiting ${WAIT_SECONDS}s for the IAM Access Management grant to propagate"
sleep "$WAIT_SECONDS"

use_key "$admin_key"
rm -f "$REFRESH_DIR/terraform.tfstate" "$REFRESH_DIR/terraform.tfstate.backup"
terraform -chdir="$REFRESH_DIR" import -input=false \
  -var "subject_service_id=${subject_service_id}" \
  -var "codeengine_region=${CODEENGINE_REGION}" \
  -var "codeengine_project_id=${CODEENGINE_PROJECT_ID}" \
  ibm_iam_service_policy.codeengine "$policy_tf_id"

refresh_plan baseline "$caller_key"

admin_apply true
echo "waiting ${WAIT_SECONDS}s for the Container Registry grant to propagate"
sleep "$WAIT_SECONDS"
refresh_plan with-registry-viewer "$caller_key"

admin_apply false
echo "waiting ${WAIT_SECONDS}s for the Container Registry grant removal to propagate"
sleep "$WAIT_SECONDS"
refresh_plan after-revoke "$caller_key"

baseline="$(cat "$OUT_DIR/baseline.exit")"
with_registry="$(cat "$OUT_DIR/with-registry-viewer.exit")"
after_revoke="$(cat "$OUT_DIR/after-revoke.exit")"

echo
echo "======== summary ========"
echo "baseline exit:     ${baseline}  (1 means refresh failed, which is the expected 403)"
echo "with registry exit: ${with_registry}  (0 means GetV2Policy succeeded and state matches)"
echo "after revoke exit: ${after_revoke}"
if [[ "$baseline" == "1" && "$with_registry" == "0" && "$after_revoke" == "1" ]]; then
  echo "RESULT: reproduced. Namespace-scoped Container Registry Viewer made the Code Engine policy readable on refresh."
else
  echo "RESULT: not reproduced. Compare out/*.log. A 403 is exit 1; a successful refresh with no drift is exit 0; drift is exit 2."
fi
echo "Clean up with: scripts/terraform_repro.sh cleanup"
