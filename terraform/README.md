# EC2 + kind fallback deploy for rajesh-grievanceapp

Use this when EKS won't spin up. It stands up **one EC2 instance** in your
existing VPC, installs Docker + kind + kubectl + Helm on it, builds the 4
microservice images from your repo, and deploys via the repo's own
**Helm chart** (`helm/rajeshapp`) — on `kind` instead of Minikube — with
one host port forwarded so you can reach `frontend-service` from your
browser.

It does **not** touch your existing `infrastructure.yml` GitHub Actions
workflow, VPC, or EKS setup — this is a separate, standalone path.

## What it creates
- A security group allowing SSH (22) and the app port (default `8080`)
- One EC2 instance (`t3.medium` by default, restricted to your allowed
  instance-type list) with **Standard** CPU credits (unlimited mode is
  never set, per policy)
- User data that: installs Docker/kubectl/kind/Helm, clones the repo,
  creates a `kind` cluster with a hostPort mapping `30080 -> 8080`,
  builds/loads the 4 service images, then runs
  `helm upgrade --install rajeshapp helm/rajeshapp -n grievance-system`

**One thing to verify yourself:** the chart's defaults in
`helm/rajeshapp/values.yaml` weren't fetchable from this environment
(GitHub blocks automated directory browsing here), so the script deploys
with the chart's own defaults as-is rather than guessed `--set`
overrides. The rest of the repo builds images as `<service>:v1` with
`imagePullPolicy: Never`, so the chart almost certainly matches — but
once the instance is up, run `helm show values helm/rajeshapp` there and
confirm the image tags/pull policy line up with what got built. If they
don't, the `--set` overrides you need are commented directly above the
`helm upgrade` line in `templates/user_data.sh.tpl`.

## Layout

```
main.tf                          root: provider + calls the module
variables.tf                     root: input vars, passed through to the module
outputs.tf                       root: passthrough outputs
terraform.tfvars.example         copy to terraform.tfvars and fill in
modules/ec2-kind-host/           the reusable module (SG + EC2 + bootstrap)
  main.tf
  variables.tf
  outputs.tf
  templates/user_data.sh.tpl
```

The module (`modules/ec2-kind-host`) has no provider block and takes no
region — it inherits the AWS provider from whatever root calls it. Reuse
it for another app/instance by pointing a second `module` block at it
with different `repo_url` / `name_prefix` values.

## Usage

```bash
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: vpc_id, subnet_id, key_name, allowed_ssh_cidr

terraform init
terraform apply
```

Or without a tfvars file:

```bash
terraform init

terraform apply \
  -var="vpc_id=vpc-xxxxxxxx" \
  -var="subnet_id=subnet-xxxxxxxx" \
  -var="key_name=your-existing-keypair" \
  -var="allowed_ssh_cidr=YOUR_IP/32"
```

Wait 3-5 minutes for user-data to finish (Docker builds + kind cluster
bring-up), then:

```bash
terraform output app_url
# open that in your browser
```

## Checking bootstrap progress / troubleshooting

```bash
ssh -i <key>.pem ubuntu@$(terraform output -raw public_ip)
sudo tail -f /var/log/user-data.log
# once done:
export KUBECONFIG=/home/ubuntu/.kube/config
kubectl get pods -n grievance-system -w
helm status rajeshapp -n grievance-system
helm get values rajeshapp -n grievance-system
```

## Notes / things to adjust for your environment
- `subnet_id` must be a **public** subnet (or one with a NAT/IGW route)
  since the instance needs outbound internet to `apt-get`, pull the
  Docker base images, and `git clone` the repo.
- `instance_type` defaults to `t3.medium` — the smallest instance that
  comfortably runs kind + 4 services + Mongo + Docker builds
  simultaneously. `t3.small`/`t2.small` will work but may be tight on
  RAM during image builds; if you must use one of those, consider
  building images on a bigger box and just running kind on the small
  one, or add swap.
- `allowed_ssh_cidr` defaults to open (`0.0.0.0/0`) — lock this to your
  IP before applying in anything but a throwaway sandbox.
- If your repo's manifests hardcode `imagePullPolicy: Never` (written
  for Minikube), that's actually fine for kind too — `kind load
  docker-image` pre-loads the image into the node's containerd, so
  "Never pull" still resolves locally.
