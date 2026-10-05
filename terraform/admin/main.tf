resource "ibm_iam_service_id" "caller" {
  name        = "${var.name_prefix}-caller"
  description = "Caller that GETs a Code Engine policy. Starts with Viewer on IAM Access Management only."
}

resource "ibm_iam_service_id" "subject" {
  name        = "${var.name_prefix}-subject"
  description = "Subject of the Code Engine policy the caller reads."
}

resource "ibm_iam_service_api_key" "caller" {
  name           = "${var.name_prefix}-caller-key"
  iam_service_id = ibm_iam_service_id.caller.iam_id
  description    = "API key for the policy-read reproduction caller."
  store_value    = true
}

resource "ibm_iam_service_policy" "caller_iam_access_management" {
  iam_id      = ibm_iam_service_id.caller.iam_id
  roles       = ["Viewer"]
  description = "Viewer on IAM Access Management"
  resources {
    service = "iam-access-management"
  }
}

resource "ibm_iam_service_policy" "subject_codeengine" {
  iam_service_id = ibm_iam_service_id.subject.id
  roles          = ["Viewer", "Writer"]

  resources {
    service              = "codeengine"
    region               = var.codeengine_region
    resource_instance_id = var.codeengine_project_id
  }
}

resource "ibm_iam_service_policy" "caller_registry" {
  count = var.grant_registry_viewer ? 1 : 0

  iam_id      = ibm_iam_service_id.caller.iam_id
  roles       = ["Viewer"]
  description = "Platform Viewer scoped to one Container Registry namespace"
  resources {
    service       = "container-registry"
    region        = var.registry_region
    resource_type = "namespace"
    resource      = var.registry_namespace
  }
}
