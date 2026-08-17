# Deployment Guide

## Prerequisites

### GitHub Secrets Required
- `DOCKERHUB_USERNAME` - Docker Hub username
- `DOCKERHUB_TOKEN` - Docker Hub access token
- `AWS_ROLE_ARN` - IAM role ARN for GitHub OIDC

### AWS Setup Required

1. **Create S3 bucket for Terraform state:**
   ```bash
   aws s3 mb s3://your-terraform-state-bucket --region us-west-2
   ```

2. **Create IAM OIDC provider for GitHub Actions:**
   - Go to AWS IAM Console → Identity providers → Add provider
   - Provider type: OpenID Connect
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`

3. **Create IAM role for GitHub Actions:**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": {
           "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
         },
         "Action": "sts:AssumeRoleWithWebIdentity",
         "Condition": {
           "StringEquals": {
             "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
           },
           "StringLike": {
             "token.actions.githubusercontent.com:sub": "repo:USERNAME/rajesh-grivenceapp:*"
           }
         }
       }
     ]
   }
   ```

4. **Attach policies to the IAM role:**
   - `AmazonEKSClusterPolicy`
   - `AmazonEKSServicePolicy`
   - `AmazonEC2FullAccess`
   - `IAMFullAccess`
   - `AmazonVPCFullAccess`

### Docker Hub Repositories
Create these repositories on Docker Hub:
- `auth-service`
- `grievance-service`
- `audit-service`
- `frontend-service`

## Terraform Commands

### Initialize and deploy infrastructure:
```bash
cd terraform/environments/prod

# Configure backend in main.tf first
terraform init
terraform plan
terraform apply
```

### Get EKS cluster credentials:
```bash
aws eks update-kubeconfig --region us-west-2 --name rajesh-grievanceapp-prod
```

## Deployment Process

### CI Pipeline
- Runs on every push/PR to main
- Tests and lints all 4 services
- Builds Docker images
- Scans with Trivy for vulnerabilities
- Validates Helm chart

### CD Pipeline
- Builds and pushes images to Docker Hub with SHA tags
- Deploys to EKS using Helm
- Verifies all deployments are healthy

## Local Development

Use existing k8s manifests for Minikube:
```bash
cd k8s
./deploy-minikube.sh
```

## Production Deployment

Use Helm for EKS:
```bash
helm upgrade --install rajeshapp ./helm/rajeshapp \
  --set auth.image.tag=<SHA> \
  --set grievance.image.tag=<SHA> \
  --set audit.image.tag=<SHA> \
  --set frontend.image.tag=<SHA>
```