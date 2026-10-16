variable "name" {
  type = string
  validation {
    condition     = length(var.name) <= 31 && can(regex("^[a-z][a-z0-9-]*$", var.name))
    error_message = "Use a lowercase role-name prefix of at most 31 characters."
  }
}
variable "cluster_name" { type = string }
variable "bucket_arn" { type = string }
variable "s3_endpoint_actions" {
  description = "Allowed transport actions from the network state, checked against workload requests."
  type        = set(string)
  default     = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"]
}
variable "bindings" {
  description = "Explicit namespace/ServiceAccount and prefix-specific object actions; empty creates no roles."
  type = map(object({
    namespace       = string
    service_account = string
    s3_access       = map(set(string))
  }))
  default = {}
  validation {
    condition = alltrue([for key, binding in var.bindings :
      length(key) <= 32 && can(regex("^[a-z][a-z0-9-]*$", key)) &&
      length(binding.namespace) <= 63 && can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", binding.namespace)) &&
      length(binding.service_account) <= 253 &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$", binding.service_account)) &&
      alltrue([for part in split(".", binding.service_account) : length(part) <= 63])
    ])
    error_message = "Use valid Kubernetes names and lowercase binding keys of at most 32 characters."
  }
  validation {
    condition = length(distinct([
      for binding in values(var.bindings) : jsonencode([binding.namespace, binding.service_account])
    ])) == length(var.bindings)
    error_message = "A namespace/ServiceAccount pair may have only one managed association."
  }
  validation {
    condition = alltrue([for binding in values(var.bindings) :
      length(binding.s3_access) > 0 && alltrue([for prefix, actions in binding.s3_access :
        can(regex("^[a-zA-Z0-9][a-zA-Z0-9/_.=-]*/$", prefix)) && !strcontains(prefix, "//") &&
        length(actions) > 0 && alltrue([for action in actions : contains([
          "s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject",
          "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"
        ], action)])
      ])
    ])
    error_message = "Provide explicit object actions on literal non-root prefixes ending in /; wildcard actions/prefixes are forbidden."
  }
  validation {
    condition = alltrue([for binding in values(var.bindings) : alltrue([
      for action in concat(["s3:ListBucket", "s3:GetBucketLocation"], flatten([
        for actions in values(binding.s3_access) : tolist(actions)
      ])) : contains(var.s3_endpoint_actions, action)
    ])])
    error_message = "Requested workload actions must also be permitted by the network S3 endpoint policy."
  }
}
