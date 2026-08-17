module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.28"

  vpc_id                         = var.vpc_id
  subnet_ids                     = var.private_subnet_ids
  control_plane_subnet_ids       = var.private_subnet_ids

  cluster_endpoint_public_access = true

  eks_managed_node_groups = {
    main = {
      name = "main-node-group"

      instance_types = ["t3.medium"]

      min_size     = 2
      max_size     = 4
      desired_size = 2
    }
  }
}

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
  cluster_name = module.eks.cluster_name
  addon_name   = "aws-ebs-csi-driver"
}