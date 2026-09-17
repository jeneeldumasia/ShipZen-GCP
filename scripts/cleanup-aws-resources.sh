#!/bin/bash
# Cleanup AWS/Karpenter resources that were synced from the old repo

echo "Cleaning up AWS/Karpenter resources from cluster..."

# Delete Karpenter NodePools
kubectl delete nodepool tenant-pool builder-pool -n shipzen-system --ignore-not-found=true

# Delete Karpenter EC2NodeClass
kubectl delete ec2nodeclass shipzen-default -n shipzen-system --ignore-not-found=true

# Delete Karpenter CRDs if they exist
kubectl delete crd nodepools.karpenter.sh --ignore-not-found=true
kubectl delete crd ec2nodeclasses.karpenter.k8s.aws --ignore-not-found=true
kubectl delete crd nodeclaims.karpenter.sh --ignore-not-found=true

# Force ArgoCD to refresh the application
kubectl delete application shipzen-platform -n argocd --ignore-not-found=true

echo "Cleanup complete! ArgoCD will recreate the application with the correct repo."
