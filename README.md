# IAM policy GET reproduction

Customer report: a service ID with **Viewer on IAM Access Management** gets **403** from `GET /v2/policies/{id}` for a Code Engine policy. After adding **platform Viewer** scoped to one Container Registry namespace, that same Code Engine policy becomes readable. Removing the registry grant brings the 403 back.

Terraform provider `IBM-Cloud/ibm` **2.5.0** hits this on refresh of `ibm_iam_service_policy`. Read calls `GetV2Policy(policyID)` in the IAM Policy Management Go SDK, which is `GET https://iam.cloud.ibm.com/v2/policies/{id}`.

Two runners exercise that call. They share the same grants:

| Step | Caller grants | Policy being read |
| --- | --- | --- |
| Baseline | Viewer on `iam-access-management` | Viewer on `codeengine` for a different service ID |
| With registry | Baseline plus Viewer on `container-registry` / `jp-tok` / namespace / `<namespace>` | Same Code Engine policy |
| After revoke | Baseline only | Same Code Engine policy |

The registry namespace does not have to exist. IAM stores `serviceName`, `region`, `resourceType`, and `resource`, and the access check uses those attributes.

## Credentials

Export an API key that can create service IDs and access policies. The scripts set both `IC_API_KEY` and `IBMCLOUD_API_KEY` to the same value when they switch from the admin key to the caller key, so provider env-var precedence cannot keep using the admin key.

```bash
export IBMCLOUD_API_KEY="..."
```

Optional overrides:

```bash
export REGISTRY_NAMESPACE="your-namespace"   # default repro-namespace
export REGISTRY_REGION="jp-tok"
export WAIT_SECONDS=45                       # terraform propagation wait
```

State, the caller API key, and provider logs are gitignored.

## Terraform, provider 2.5.0

`terraform/admin` creates the caller service ID, its API key, the IAM Access Management Viewer policy, and the Code Engine policy. `grant_registry_viewer` adds or removes the registry policy.

`terraform/refresh` contains only `ibm_iam_service_policy.codeengine`. An admin imports it, then each phase runs `terraform plan -refresh-only` as the caller. That plan calls the provider Read hook and does not create or update the policy.

```bash
scripts/terraform_repro.sh
scripts/terraform_repro.sh cleanup
```

Provider debug is written to `out/<phase>.log` with `Authorization` redacted. Refresh exit codes:

- `1` — Read failed. For this test that is the 403.
- `0` — `GetV2Policy` succeeded and the policy still matches the config.
- `2` — Read succeeded, and Terraform wants to change the resource. Check the log before treating that as the customer bug.

A reproduced run is exit `1`, then `0`, then `1`.

## Python SDK

The service client is `ibm-platform-services` (`IamPolicyManagementV1`). It uses `ibm-cloud-sdk-core` for auth and HTTP. Setup calls v1 `create_policy`, matching provider 2.5.0 when the policy has no rule conditions. The probe calls `get_v2_policy`, prints the request and response, and redacts API keys and bearer tokens.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r python/requirements.txt
python python/reproduce_policy_get.py run --registry-namespace your-namespace
python python/reproduce_policy_get.py cleanup
```

`run` waits `--initial-wait` seconds (default 20), then does one baseline GET. The registry and revoke phases poll until HTTP 200 or 403, or until `--timeout` seconds (default 180).

Exit `2` means the 403 → 200 → 403 pattern happened. Exit `0` means the calls finished with a different pattern. Caller credentials are stored in `python/out/state.json`.

## What a hit looks like

On the middle phase the response body is still the Code Engine policy (`serviceName=codeengine`). The registry grant did not retarget it. Only the caller's ability to read it changed.
