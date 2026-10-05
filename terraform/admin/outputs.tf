output "caller_iam_id" {
  value = ibm_iam_service_id.caller.iam_id
}

output "caller_api_key" {
  value     = ibm_iam_service_api_key.caller.apikey
  sensitive = true
}

output "subject_iam_id" {
  value = ibm_iam_service_id.subject.iam_id
}

output "subject_service_id" {
  description = "Service ID value used by iam_service_id. Provider 2.5.0 stores the policy id as iam-<this>/<policy_id>."
  value       = ibm_iam_service_id.subject.id
}

output "codeengine_policy_terraform_id" {
  description = "ibm_iam_service_policy id. Provider 2.5.0 splits this and calls GetV2Policy with the policy id."
  value       = ibm_iam_service_policy.subject_codeengine.id
}

output "registry_policy_terraform_id" {
  value = try(ibm_iam_service_policy.caller_registry[0].id, null)
}
