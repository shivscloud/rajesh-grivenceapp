# What I checked, what I fixed, and how to actually run this

## Environment limits — read this first
I reviewed and statically validated every file in this repo, but I could **not**
run `terraform apply`, `docker build`, `kind create cluster`, or `helm install`
myself: my sandbox has no AWS credentials, no outbound network access, and none
of terraform/docker/helm/kubectl installed. So "tested end-to-end on a live EKS
cluster" isn't something I can honestly claim. What I *did* do:

- Parsed all 19 raw `k8s/*.yaml` manifests and all `.github/workflows/*.yml`
  files with a YAML parser — all valid syntax, no errors.
- Read every Helm template, every `.tf` file, both Dockerfile patterns, and the
  EC2 bootstrap script line by line, cross-checking image names, ports, env
  vars, ConfigMap/Secret keys, and module variable wiring against each other.
- Fixed the bugs that would have actually broken a deployment (below).

You'll need to run `terraform apply` yourself with real AWS credentials — I
can't do that part for you from here.

## Bugs found and fixed

1. **Critical — image tag mismatch in the EC2/kind bootstrap script**
   (`terraform/modules/ec2-kind-host/templates/user_data.sh.tpl`).
   It built images as `auth-service:v1` (no registry prefix), but
   `helm/rajeshapp/values.yaml` defaults to `image.registry: rajeshapp`, so the
   chart's Deployment template requests `rajeshapp/auth-service:v1`. Every raw
   manifest in `k8s/` and `deploy-minikube.sh` already use the
   `rajeshapp/<service>:v1` naming — only this script was inconsistent. As
   written, every pod would have hit `ImagePullBackOff` on first boot. Fixed:
   the script now builds/loads `rajeshapp/<service>:v1` and passes
   `--set image.registry=rajeshapp --set image.tag=v1 --set image.pullPolicy=IfNotPresent`
   explicitly to `helm upgrade --install`, so it can't drift again even if
   `values.yaml` changes later.

2. **Misleading comment** in `terraform/modules/eks/main.tf` — the node group
   had `capacity_type = "ON_DEMAND"` next to a comment claiming "~60-70%
   cheaper than On-Demand" (that saving only applies to `"SPOT"`). Left the
   value as `ON_DEMAND` (more reliable for a first run) and corrected the
   comment to say how to switch to `SPOT` if you want the cost saving instead.

## Things I could *not* verify (worth checking before you rely on this in prod)

- **`terraform/modules/eks/main.tf` pins `terraform-aws-modules/eks/aws ~> 19.0`
  with `cluster_version = "1.33"`.** I can't confirm from here whether the v19
  module release supports that new a Kubernetes version — the module's support
  matrix moves faster than my knowledge is current. Run `terraform init` and
  `terraform validate` in `terraform/environments/prod` first; if the module
  rejects the version, bump either the module version constraint or
  `cluster_version` to something the module docs confirm support for.
- **`create_iam_role = false` for both the cluster and node group**, pointing
  at `arn:aws:iam::<account>:role/eksClusterRole` and
  `.../AmazonEKSNodeRole`. These IAM roles are **not created by this Terraform**
  — they must already exist in your AWS account with the right trust policy
  and managed policies attached, or `apply` will fail. If they don't exist
  yet, either create them first or flip `create_iam_role = true` and drop the
  `iam_role_arn` lines so the module creates them for you.
- The EC2/kind path (root `terraform/`) expects an **existing VPC + public
  subnet** (`var.vpc_id` / `var.subnet_id` in `terraform.tfvars`) — it does not
  create its own network. The full-EKS path
  (`terraform/environments/prod`) does create its own VPC via the `vpc`
  module. Pick the one that matches what you actually want deployed; they're
  independent, not layered on each other.
- S3 backend in `terraform/environments/prod/main.tf` references a bucket
  (`rajesh-grievanceapp-tfstate`) that has to exist before `terraform init`
  will succeed — the state-locking DynamoDB table is also commented out.
  Create the bucket (and uncomment/create the lock table) first, or switch to
  local state for a first test run.

## How to run it yourself

**Path A — EC2 + kind (fastest, cheapest, single instance):**
```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # fill in your vpc_id/subnet_id/key_name
terraform init
terraform plan
terraform apply
# then: ssh -i <key>.pem ubuntu@<public_ip>, tail -f /var/log/user-data.log
# app_url output tells you the URL once bootstrap finishes
```

**Path B — full EKS cluster:**
```bash
cd terraform/environments/prod
# create the S3 state bucket first, or comment out the backend block for local state
terraform init
terraform plan
terraform apply
aws eks update-kubeconfig --name rajesh-grievanceapp-prod --region us-west-2
helm upgrade --install rajeshapp ../../../helm/rajeshapp \
  --namespace grievance-system --create-namespace --wait --timeout 5m
```

**Local test without any cloud, before you spend money on either path above:**
```bash
docker compose up --build
# open http://localhost:5000
```

## Round 2 — workflow fixes (infra + deploy)

Same limitation applies: I can't fire a real GitHub Actions run without your
repo/secrets/AWS account, so this is a full read-through + fix, not a live run.

1. **`deploy.yml` was deploying the wrong image, silently.** It passed
   `--set auth.image.repository=...`, `--set grievance.image.repository=...`
   etc., but `helm/rajeshapp/values.yaml` only has one global `image.registry`
   + `image.tag` (looped per service in the template) — there's no
   `auth.image.*` key in this chart. Helm just added those as unused extra
   keys and quietly ignored them, so every deploy kept using the chart's
   default `rajeshapp/<service>:v1` instead of the `github.sha`-tagged image
   CI had just built and pushed. **Fixed** to `--set image.registry=<dockerhub
   username> --set image.tag=<sha>`, which matches how `ci.yml` actually tags
   pushed images (`<DOCKERHUB_USERNAME>/<service>:<sha>`) and how the chart
   renders them. Also added `--namespace rajeshapp --create-namespace` for a
   clean first deploy.
2. **Region mismatch.** `deploy.yml` used `AWS_REGION: us-west-2`, but the
   Terraform S3 backend and `infrastructure.yml` both use `us-east-1`, and
   `terraform/environments/prod` had no explicit AWS provider block (region
   was only ever set implicitly through the CI action's env var, so a local
   `terraform apply` with no env vars set could pick a different region than
   CI did). `aws eks update-kubeconfig --region us-west-2` would have looked
   for the cluster in the wrong region and failed outright. Fixed: added an
   explicit `provider "aws" { region = var.aws_region }` block, changed
   `aws_region`'s default to `us-east-1`, and changed `deploy.yml`'s
   `AWS_REGION` to `us-east-1` — all three now agree.
3. **`infrastructure.yml`'s pull_request trigger was inverted.** It had
   `paths-ignore: [terraform/**]` on the `pull_request` block — meaning a PR
   that only touched Terraform never triggered this workflow at all, so infra
   changes got zero linting or plan review before merge. Fixed to `paths:
   [terraform/**]`, matching the `push` trigger.
4. **`terraform apply` had no event guard.** Once the PR trigger above is
   fixed, `pull_request` events would reach the `terraform` job with nothing
   stopping the apply step — a PR could trigger a real
   `terraform apply -auto-approve` before anyone reviewed the plan. Added
   `if: github.event_name != 'pull_request'` to the apply step, so PRs only
   ever get a plan; only a push to main/master (or a completed CI run) can
   apply.
5. **Deleted `terraform.yml`, `terraform-plan.yml`, `terraform-apply.yml`.**
   All three triggered on the same `push`/`pull_request` to `terraform/**`
   paths as `infrastructure.yml` — a single push to `terraform/**` on `main`
   would fire `infrastructure.yml` *and* `terraform-apply.yml` at the same
   time, both trying to `terraform apply` against the same S3-backed state
   with no lock table configured. `infrastructure.yml` already does
   everything those three did (plus TFLint, Checkov, S3 bucket bootstrap), so
   it's now the single source of truth for Terraform in CI — "single build"
   instead of four workflows racing each other.

### Still worth doing yourself
- The S3 backend's `dynamodb_table` (state lock) is commented out in
  `terraform/environments/prod/main.tf`. With only one workflow applying now
  this is lower risk than before, but a lock table is still cheap insurance
  against two people/pipelines running `apply` at once — worth uncommenting
  once you've created that DynamoDB table.
- `deploy.yml` still expects `secrets.AWS_ROLE_ARN` and
  `secrets.DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` to be set in your repo's
  Actions secrets — nothing here creates those for you.
