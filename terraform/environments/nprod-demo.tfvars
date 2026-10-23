# nprod-demo (Argolis) environment.
project_id  = "nprod-demo"
region      = "us-central1"
environment = "dev"

# The operator account in this project cannot set IAM on individual resources
# (Cloud Run service, secret, service accounts) nor create WIF pools, so
# resource-scoped roles fall back to project level and GitHub WIF is disabled.
# In a project with a full admin, use iam_scope = "resource" and enable_github_wif = true.
iam_scope         = "project"
enable_github_wif = false

github_repository = "thiago-a-azevedo/anatel"

# alert_email and billing_account_id live in the git-ignored
# environments/nprod-demo.private.tfvars (see private.tfvars.example).

monthly_budget_usd = 200

force_destroy_buckets  = true
reports_retention_days = 90
