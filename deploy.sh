#!/usr/bin/env bash
set -euo pipefail

# Config (override via env): REGION, PROJECT, IMG_TAG
REGION=${REGION:-us-east-1}
PROJECT=${PROJECT:-marketplace-intel}
IMG_TAG=${IMG_TAG:-$(date +%Y%m%d%H%M%S)}

echo "==> Terraform init & create ECR repo"
terraform -chdir=terraform init -upgrade
terraform -chdir=terraform apply -auto-approve -target=aws_ecr_repository.api -var="region=$REGION" -var="project_name=$PROJECT"

ECR_URL=$(terraform -chdir=terraform output -raw ecr_repo_url)
AWS_ACCOUNT=$(echo "$ECR_URL" | cut -d'.' -f1)
ECR_REGISTRY=$(echo "$ECR_URL" | cut -d'/' -f1)

echo "==> Build & push image to $ECR_URL:$IMG_TAG"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker build -f Dockerfile.api -t "$ECR_URL:$IMG_TAG" .
docker push "$ECR_URL:$IMG_TAG"

echo "==> Terraform apply full stack"
terraform -chdir=terraform apply -auto-approve \
  -var="image_uri=$ECR_URL:$IMG_TAG" \
  -var="region=$REGION" \
  -var="project_name=$PROJECT"

ALB_DNS=$(terraform -chdir=terraform output -raw alb_dns_name)

cat <<MSG

Deployed ✅
Health:  http://$ALB_DNS/health
Ask:     http://$ALB_DNS/ask?q=Top%203%20selling%20electronics%20products%20in%20Q3

MSG
