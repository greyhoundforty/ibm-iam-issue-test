terraform {
  required_version = ">= 1.5.0"

  required_providers {
    ibm = {
      source  = "IBM-Cloud/ibm"
      version = "= 2.5.0"
    }
  }
}

provider "ibm" {
  region = var.region
}
