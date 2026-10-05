# IAM policy read test

We tried to reproduce this behavior on 30 September 2026 with Terraform provider `IBM-Cloud/ibm` **2.5.0**:

1. A service ID has platform **Viewer** on IAM Access Management (`iam-access-management`).
2. A separate policy grants platform **Viewer** on Code Engine (`codeengine`).
3. As the test service ID, `GET /v2/policies/{policy-id}` for that Code Engine policy returns **403**.
4. The test service ID is also granted platform **Viewer** on one Container Registry namespace (`container-registry`, region `jp-tok`, resource type `namespace`).
5. The same GET becomes readable, even though the policy still targets Code Engine.
6. Removing the registry grant makes the GET return **403** again.

In the provider, refresh of `ibm_iam_service_policy` calls `GetV2Policy(policyID)` in the IAM Policy Management Go SDK. That is `GET https://iam.cloud.ibm.com/v2/policies/{id}`.

## Result

The GET stayed **403** in every phase. Adding and removing the Container Registry grant did not change it.

We ran the Terraform test twice. The first used the namespace name `repro-namespace` as a policy attribute only. The second used an existing namespace, `rst-iamdemo-ns`, in `jp-tok`. Both runs denied the read.

Second run, policy `7ff05456-8650-445b-831f-3d49c32426d7` (Code Engine Viewer):

| Phase | Time (EDT) | HTTP | IAM trace |
| --- | --- | --- | --- |
| Baseline, IAM Access Management Viewer only | 13:25:41 | 403 | `73a61afa2fcc40249d533c96d979bea9` |
| With Container Registry namespace Viewer | 13:26:36 | 403 | `21c8fb6281454c2f9c3bde4a9313b9da` |
| After the registry grant was removed | 13:27:28 | 403 | `6475cac99b544b0a84c57ab8459c5b43` |

IBM returned:

```json
{
  "errors": [
    {
      "code": "insufficent_permissions",
      "message": "You are not allowed to retrieve the requested policy."
    }
  ],
  "status_code": 403
}
```

`Ibm-Cloud-Service-Name: iam-access-management` on that response is the API that answered. The policy resource was still `codeengine`.

A reproduction of the reported behavior would be **403**, then **200**, then **403**. We observed **403**, **403**, **403**.

The Code Engine policy in those runs was account-wide platform Viewer. It was not scoped to a project.

## Follow-up configuration

The customer policy that showed the behavior is Viewer and Writer on one Code Engine project, created with `iam_service_id`. The test now uses that shape:

```hcl
resource "ibm_iam_service_policy" "subject_codeengine" {
  iam_service_id = ibm_iam_service_id.subject.id
  roles          = ["Viewer", "Writer"]

  resources {
    service              = "codeengine"
    region               = "jp-tok"
    resource_instance_id = "353e8ce5-42e6-49b6-b1b2-b7f1feff343a"
  }
}
```

The registry grant in the middle phase is platform Viewer on `container-registry`, region `jp-tok`, resource type `namespace`, resource `dreamvu-data-mover`. Both values are IAM attributes. The test does not create the project or the namespace.

## What the test creates

| Resource | Who it is attached to | Role | Target |
| --- | --- | --- | --- |
| Caller service ID and its API key | The identity that calls the GET |  |  |
| Access policy | Caller | Platform Viewer | `serviceName=iam-access-management` |
| Subject service ID | A different identity |  |  |
| Access policy, this is the ID we GET | Subject | Platform Viewer and service Writer | `serviceName=codeengine`, `region=jp-tok`, `serviceInstance=353e8ce5-42e6-49b6-b1b2-b7f1feff343a` |
| Access policy, present only in the middle phase | Caller | Platform Viewer | `serviceName=container-registry`, `region=jp-tok`, `resourceType=namespace`, `resource=dreamvu-data-mover` |

## How the GET is authenticated

The administrator API key and the test service ID API key are different credentials.

- The administrator key creates the service IDs, the caller API key, and the policies. It also imports the Code Engine policy into Terraform state. That import calls the same GET, and it succeeds because the administrator can read the policy.
- The test call uses the caller service ID API key. Terraform provider 2.5.0 reads `IC_API_KEY` or `IBMCLOUD_API_KEY`. Before each refresh, the test script sets both variables to the caller key created in the admin stack (`terraform output -raw caller_api_key`). The refresh command is `terraform plan -refresh-only` on a stack whose only resource is that `ibm_iam_service_policy`. Refresh calls `GetV2Policy`. It does not create or update the policy.
- The Python client does the same split. Setup uses the administrator key from the environment. The probe builds a new IAM Policy Management client with the caller API key and calls `get_v2_policy`.

The 403 on refresh, after a successful import with the administrator key, shows that the GET ran as the caller service ID.

## Reproduce it

Use an API key that can create service IDs and access policies. Terraform 1.5 or newer is required. The provider is pinned to `IBM-Cloud/ibm` 2.5.0.

Terraform:

```bash
export IBMCLOUD_API_KEY="..."
export REGISTRY_NAMESPACE="dreamvu-data-mover"   # default
export REGISTRY_REGION="jp-tok"                  # default
export CODEENGINE_PROJECT_ID="353e8ce5-42e6-49b6-b1b2-b7f1feff343a"
scripts/terraform_repro.sh
scripts/terraform_repro.sh cleanup
```

Refresh exit codes: **1** means the read failed (the 403 in this test), **0** means `GetV2Policy` succeeded and the policy still matches the config. Provider logs are written to `out/<phase>.log`.

Python, same grants and the same GET, with the request and response printed:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r python/requirements.txt
python python/reproduce_policy_get.py run --brief --registry-namespace dreamvu-data-mover --codeengine-project-id 353e8ce5-42e6-49b6-b1b2-b7f1feff343a
python python/reproduce_policy_get.py cleanup
```

Setup creates the policy with v1 `create_policy`, which is the create path provider 2.5.0 uses when the policy has no rule conditions. The probe is v2 `GET /v2/policies/{id}`. Created names are prefixed with `dreamvu-iam-repro`.

## Details worth comparing

The follow-up test matches the customer resource on these points:

- Caller and policy subject are two different service IDs.
- The Code Engine policy uses `iam_service_id`.
- Roles are platform Viewer and service Writer.
- The Code Engine target is `jp-tok` and project `353e8ce5-42e6-49b6-b1b2-b7f1feff343a`.
- The registry grant is namespace `dreamvu-data-mover` in `jp-tok`.
- The call is `GET /v2/policies/{id}` during `ibm_iam_service_policy` refresh.

The September runs above used an account-wide Code Engine Viewer policy, so they do not answer this comparison.
