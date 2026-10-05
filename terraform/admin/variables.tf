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
  default     = "dreamvu-data-mover"
}

variable "codeengine_region" {
  type        = string
  description = "Region on the Code Engine policy."
  default     = "jp-tok"
}

variable "codeengine_project_id" {
  type        = string
  description = "Code Engine project GUID stored as serviceInstance on the policy. This is the project from the customer resource."
  default     = "353e8ce5-42e6-49b6-b1b2-b7f1feff343a"
}

variable "grant_registry_viewer" {
  type        = bool
  description = "When true, the caller service ID also has platform Viewer on one Container Registry namespace."
  default     = false
}
