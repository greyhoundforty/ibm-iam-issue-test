variable "region" {
  type    = string
  default = "jp-tok"
}

variable "subject_service_id" {
  type        = string
  description = "ibm_iam_service_id.id of the service ID that owns the Code Engine policy."
}

variable "codeengine_region" {
  type    = string
  default = "jp-tok"
}

variable "codeengine_project_id" {
  type        = string
  description = "Code Engine project GUID on the policy being refreshed."
}
