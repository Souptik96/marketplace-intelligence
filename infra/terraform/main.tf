terraform {
  required_version = ">= 1.7.0"
  required_providers { aws = { source = "hashicorp/aws", version = "~> 5.50" } }
}
provider "aws" { region = var.region }

locals { name = var.project_name  tags = { Project = var.project_name } }

# ECR
resource "aws_ecr_repository" "api" {
  name = "${local.name}-api"
  image_tag_mutability = "MUTABLE"
  force_delete = true
  image_scanning_configuration { scan_on_push = true }
  tags = local.tags
}

# VPC + subnets + IGW + route
resource "aws_vpc" "this" {
  cidr_block = var.vpc_cidr
  enable_dns_support = true
  enable_dns_hostnames = true
  tags = merge(local.tags, { Name = "${local.name}-vpc" })
}
resource "aws_internet_gateway" "igw" { vpc_id = aws_vpc.this.id  tags = local.tags }
resource "aws_subnet" "public_a" {
  vpc_id = aws_vpc.this.id
  cidr_block = "10.20.1.0/24"
  map_public_ip_on_launch = true
  availability_zone = "${var.region}a"
  tags = merge(local.tags, { Name = "${local.name}-pub-a" })
}
resource "aws_subnet" "public_b" {
  vpc_id = aws_vpc.this.id
  cidr_block = "10.20.2.0/24"
  map_public_ip_on_launch = true
  availability_zone = "${var.region}b"
  tags = merge(local.tags, { Name = "${local.name}-pub-b" })
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route { cidr_block = "0.0.0.0/0"  gateway_id = aws_internet_gateway.igw.id }
  tags = local.tags
}
resource "aws_route_table_association" "a" { subnet_id = aws_subnet.public_a.id route_table_id = aws_route_table.public.id }
resource "aws_route_table_association" "b" { subnet_id = aws_subnet.public_b.id route_table_id = aws_route_table.public.id }

# SGs
resource "aws_security_group" "alb" {
  name = "${local.name}-alb-sg"; vpc_id = aws_vpc.this.id
  ingress { from_port=80 to_port=80 protocol="tcp" cidr_blocks=["0.0.0.0/0"] }
  egress  { from_port=0  to_port=0  protocol="-1"  cidr_blocks=["0.0.0.0/0"] }
  tags = local.tags
}
resource "aws_security_group" "ecs" {
  name = "${local.name}-ecs-sg"; vpc_id = aws_vpc.this.id
  ingress { from_port=8000 to_port=8000 protocol="tcp" security_groups=[aws_security_group.alb.id] }
  egress  { from_port=0    to_port=0    protocol="-1"  cidr_blocks=["0.0.0.0/0"] }
  tags = local.tags
}

# ALB
resource "aws_lb" "this" {
  name = "${local.name}-alb"
  internal = false
  load_balancer_type = "application"
  security_groups = [aws_security_group.alb.id]
  subnets = [aws_subnet.public_a.id, aws_subnet.public_b.id]
  tags = local.tags
}
resource "aws_lb_target_group" "api" {
  name        = "${local.name}-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.this.id
  target_type = "ip"
  health_check { path="/health" interval=30 healthy_threshold=2 unhealthy_threshold=3 matcher="200" }
  tags = local.tags
}
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port = 80
  protocol = "HTTP"
  default_action { type = "forward" target_group_arn = aws_lb_target_group.api.arn }
}

# ECS + task
resource "aws_ecs_cluster" "this" { name = "${local.name}-cluster"  tags = local.tags }

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement { actions=["sts:AssumeRole"] principals { type="Service" identifiers=["ecs-tasks.amazonaws.com"] } }
}
resource "aws_iam_role" "task_exec" { name = "${local.name}-task-exec" assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json  tags = local.tags }
resource "aws_iam_role_policy_attachment" "task_exec_policy" {
  role = aws_iam_role.task_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_cloudwatch_log_group" "api" { name = "/ecs/${local.name}-api" retention_in_days = 7  tags = local.tags }

locals {
  container_env = concat([
    { name = "LLM_PROVIDER", value = var.llm_provider },
    { name = "LLM_MODEL_GEN", value = var.llm_model_gen },
    { name = "LLM_MODEL_REV", value = var.llm_model_rev }
  ],
  var.hf_api_key != "" ? [{ name = "HF_API_KEY", value = var.hf_api_key }] : [],
  var.fireworks_api_key != "" ? [{ name = "FIREWORKS_API_KEY", value = var.fireworks_api_key }] : []
  )
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.task_exec.arn
  container_definitions    = jsonencode([{
    name  = "api"
    image = var.image_uri != "" ? var.image_uri : "public.ecr.aws/amazonlinux/amazonlinux:latest"
    essential = true
    portMappings = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "ecs"
      }
    }
    environment = local.container_env
  }])
  runtime_platform { cpu_architecture="X86_64" operating_system_family="LINUX" }
  tags = local.tags
}

resource "aws_ecs_service" "api" {
  name            = "${local.name}-svc"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = [aws_subnet.public_a.id, aws_subnet.public_b.id]
    security_groups = [aws_security_group.ecs.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.http]
  tags = local.tags
}