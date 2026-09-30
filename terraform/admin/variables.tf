variable "region" {
  type        = string
  description = "Provider region. IAM itself is global; this does not change the policy resource attributes."
  default     = "jp-tok"
}

variable "name_prefix" {
  type        = string
  description = "Prefix for the service IDs created for this reproduction."
  default     = "dreamvu-iam-repro"
}

variable "registry_region" {
  type        = string
  description = "Region attribute on the Container Registry Viewer policy."
  default     = "jp-tok"
}

variable "registry_namespace" {
  type        = string
  description = "Container Registry namespace attribute. The namespace does not have to exist; IAM stores the attribute and the access decision uses it."
  default     = "repro-namespace"
}

variable "grant_registry_viewer" {
  type        = bool
  description = "When true, the caller service ID also has platform Viewer on one Container Registry namespace."
  default     = false
}
