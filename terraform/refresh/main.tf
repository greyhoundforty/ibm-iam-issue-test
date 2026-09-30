# Refresh-only reproduction of ibm_iam_service_policy in IBM-Cloud/ibm 2.5.0.
#
# Provider Read calls IAMPolicyManagementV1.GetV2Policy(policyID), which is
# GET /v2/policies/{id}. This configuration is imported by an administrator,
# then planned with -refresh-only using the caller service ID API key.
#
# Do not apply this stack as the caller. Apply would try to create or update
# the policy. The runner only uses plan -refresh-only.

resource "ibm_iam_service_policy" "codeengine" {
  iam_id      = var.subject_iam_id
  roles       = ["Viewer"]
  description = "Code Engine policy read by the caller service ID during refresh"
  resources {
    service = "codeengine"
  }
}
