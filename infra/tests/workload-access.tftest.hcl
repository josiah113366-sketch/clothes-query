mock_provider "aws" {}

run "directory_probe_is_exact_and_read_only" {
  command = plan
  module { source = "../modules/workload-access" }
  variables {
    bindings = { stream = {
      namespace          = "pipelines", service_account = "stream-driver"
      s3_access          = { "gold_b/_checkpoints/stream/" = ["s3:GetObject", "s3:PutObject"] }
      s3_directory_reads = ["gold_b/_checkpoints/stream"]
    } }
  }
  assert {
    condition = length([for s in jsondecode(aws_iam_role_policy.s3["stream"].policy).Statement : s
      if s.Resource == ["arn:aws:s3:::test-data-bucket/gold_b/_checkpoints/stream"] && s.Action == ["s3:GetObject"]
    ]) == 1
    error_message = "Directory HEAD access must use one exact resource with GetObject only."
  }
  assert {
    condition = alltrue([for s in jsondecode(aws_iam_role_policy.s3["stream"].policy).Statement :
      !contains(s.Action, "s3:ListBucket") || try(toset(s.Condition.StringLike["s3:prefix"]) == toset([
        "gold_b/_checkpoints/stream/*", "gold_b/_checkpoints/stream"
      ]), false)
    ])
    error_message = "Bucket listing must not expand to sibling checkpoints."
  }
}

run "reject_directory_probe_outside_owned_prefix" {
  command = plan
  module { source = "../modules/workload-access" }
  variables {
    bindings = { stream = {
      namespace          = "pipelines", service_account = "stream-driver"
      s3_access          = { "gold_b/_checkpoints/stream/" = ["s3:GetObject"] }
      s3_directory_reads = ["ground_truth"]
    } }
  }
  expect_failures = [var.bindings]
}

variables {
  name         = "test-data"
  cluster_name = "test-cluster"
  bucket_arn   = "arn:aws:s3:::test-data-bucket"
  s3_endpoint_actions = [
    "s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation",
    "s3:GetObjectVersion", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"
  ]
}

run "no_roles_without_explicit_bindings" {
  command = plan
  module { source = "../modules/workload-access" }
  assert {
    condition = (
      length(aws_iam_role.this) == 0 && length(aws_iam_role_policy.s3) == 0 &&
      length(aws_eks_pod_identity_association.this) == 0
    )
    error_message = "Preparation alone must not grant any data workload AWS permissions."
  }
}

run "writer_and_reader_have_separate_prefix_permissions" {
  command = plan
  module { source = "../modules/workload-access" }
  variables {
    bindings = {
      consumer = {
        namespace       = "ingest"
        service_account = "bronze-consumer"
        s3_access       = { "bronze/" = ["s3:PutObject", "s3:AbortMultipartUpload"] }
      }
      reader = {
        namespace       = "query"
        service_account = "gold-reader"
        s3_access       = { "silver/" = ["s3:GetObject"], "gold/" = ["s3:GetObject"] }
      }
    }
  }
  assert {
    condition = (
      toset(flatten([for s in jsondecode(aws_iam_role_policy.s3["consumer"].policy).Statement : s.Action])) == toset(["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListBucket", "s3:GetBucketLocation"]) &&
      toset(flatten([for s in jsondecode(aws_iam_role_policy.s3["reader"].policy).Statement : s.Action])) == toset(["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"])
    )
    error_message = "A writer must not automatically gain read/delete, and a reader must not gain write/delete."
  }
  assert {
    condition = (
      toset(flatten([for s in jsondecode(aws_iam_role_policy.s3["consumer"].policy).Statement : s.Resource if contains(s.Action, "s3:PutObject")])) == toset(["arn:aws:s3:::test-data-bucket/bronze/*"]) &&
      toset(flatten([for s in jsondecode(aws_iam_role_policy.s3["reader"].policy).Statement : s.Resource if contains(s.Action, "s3:GetObject")])) == toset(["arn:aws:s3:::test-data-bucket/silver/*", "arn:aws:s3:::test-data-bucket/gold/*"])
    )
    error_message = "Object access must be limited to each workload's explicit prefixes."
  }
  assert {
    condition = alltrue([for key, binding in var.bindings :
      jsondecode(aws_iam_role.this[key].assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/kubernetes-namespace"] == binding.namespace &&
      jsondecode(aws_iam_role.this[key].assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/kubernetes-service-account"] == binding.service_account &&
      aws_eks_pod_identity_association.this[key].namespace == binding.namespace &&
      aws_eks_pod_identity_association.this[key].service_account == binding.service_account &&
      aws_eks_pod_identity_association.this[key].cluster_name == "test-cluster" &&
      alltrue([for s in jsondecode(aws_iam_role_policy.s3[key].policy).Statement :
        !contains(s.Action, "s3:ListBucket") || try(toset(s.Condition.StringLike["s3:prefix"]) == toset([for prefix in keys(binding.s3_access) : "${prefix}*"]), false)
      ])
    ])
    error_message = "Trust, association and bucket listing must follow the workload identity and prefix contract."
  }
}

run "reject_wildcard_prefix" {
  command = plan
  module { source = "../modules/workload-access" }
  variables {
    bindings = { consumer = {
      namespace = "ingest", service_account = "consumer"
      s3_access = { "*/" = ["s3:PutObject"] }
    } }
  }
  expect_failures = [var.bindings]
}

run "reject_wildcard_actions" {
  command = plan
  module { source = "../modules/workload-access" }
  variables {
    bindings = { consumer = {
      namespace = "ingest", service_account = "consumer"
      s3_access = { "bronze/" = ["s3:*"] }
    } }
  }
  expect_failures = [var.bindings]
}

run "reject_duplicate_service_account_association" {
  command = plan
  module { source = "../modules/workload-access" }
  variables {
    bindings = {
      first = {
        namespace = "ingest", service_account = "consumer"
        s3_access = { "bronze/" = ["s3:PutObject"] }
      }
      second = {
        namespace = "ingest", service_account = "consumer"
        s3_access = { "gold/" = ["s3:GetObject"] }
      }
    }
  }
  expect_failures = [var.bindings]
}

run "reject_action_blocked_by_network_endpoint" {
  command = plan
  module { source = "../modules/workload-access" }
  variables {
    s3_endpoint_actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"]
    bindings = { consumer = {
      namespace = "ingest", service_account = "consumer"
      s3_access = { "bronze/" = ["s3:PutObject", "s3:AbortMultipartUpload"] }
    } }
  }
  expect_failures = [var.bindings]
}
