output "alb_dns_name" { value = aws_lb.this.dns_name }
output "ecr_repo_url" { value = aws_ecr_repository.api.repository_url }
