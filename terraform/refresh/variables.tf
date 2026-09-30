variable "region" {
  type    = string
  default = "jp-tok"
}

variable "subject_iam_id" {
  type        = string
  description = "IAM ID of the service ID that owns the Code Engine policy."
}
