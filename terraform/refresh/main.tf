# Refresh-only reproduction of ibm_iam_service_policy in IBM-Cloud/ibm 2.5.0.
#
# Provider Read calls IAMPolicyManagementV1.GetV2Policy(policyID), which is
# GET /v2/policies/{id}. This configuration is imported by an administrator,
# then planned with -refresh-only using the caller service ID API key.
#
# The resource arguments match the customer policy: iam_service_id, Viewer
# and Writer, and a Code Engine project in jp-tok.
#
# Do not apply this stack as the caller. Apply would try to create or update
# the policy. The runner only uses plan -refresh-only.

resource "ibm_iam_service_policy" "codeengine" {
  iam_service_id = var.subject_service_id
  roles          = ["Viewer", "Writer"]

  resources {
    service              = "codeengine"
    region               = var.codeengine_region
    resource_instance_id = var.codeengine_project_id
  }
}
