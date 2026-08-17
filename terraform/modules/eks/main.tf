module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.33"

  vpc_id                    = var.vpc_id
  subnet_ids                = var.public_subnet_ids   
  control_plane_subnet_ids  = var.public_subnet_ids

  cluster_endpoint_public_access = true

  create_iam_role = false
  iam_role_arn    = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/eksClusterRole"

  # Stop the module creating its own KMS key
  create_kms_key             = false
  cluster_encryption_config  = {}

  # Stop the module creating its own CloudWatch log group
  create_cloudwatch_log_group = false

  # Required for the EBS CSI driver's IRSA role below to work
  enable_irsa = true

  eks_managed_node_groups = {
    main = {
      name = "main-node-group"

      instance_types  = ["t3.small"]
      capacity_type   = "ON_DEMAND"   # switch to "SPOT" for ~60-70% cheaper nodes (adds interruption risk)
      create_iam_role = false

      min_size     = 1
      max_size     = 1
      desired_size = 1

      subnet_ids = var.public_subnet_ids

      disk_size = 20   # smaller root volume than module default, gp3

      iam_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/AmazonEKSNodeRole"
    }
  }
}

data "aws_caller_identity" "current" {}

############################
# ADDONS
############################

resource "aws_eks_addon" "coredns" {
  cluster_name = module.eks.cluster_name
  addon_name   = "coredns"
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name = module.eks.cluster_name
  addon_name   = "kube-proxy"
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name = module.eks.cluster_name
  addon_name   = "vpc-cni"
}

resource "aws_eks_addon" "ebs_csi_driver" {
  cluster_name             = module.eks.cluster_name
  addon_name               = "aws-ebs-csi-driver"
  service_account_role_arn = aws_iam_role.ebs_csi_irsa.arn

  depends_on = [module.eks.eks_managed_node_groups]
}

############################
# IRSA ROLE FOR EBS CSI DRIVER
############################

data "aws_iam_policy_document" "ebs_csi_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(module.eks.cluster_oidc_issuer_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(module.eks.cluster_oidc_issuer_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_csi_irsa" {
  name               = "${var.cluster_name}-ebs-csi-irsa"
  assume_role_policy = data.aws_iam_policy_document.ebs_csi_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ebs_csi_policy" {
  role       = aws_iam_role.ebs_csi_irsa.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}