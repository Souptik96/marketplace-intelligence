variable "project_name" { type = string  default = "marketplace-intel" }
variable "region"       { type = string  default = "ap-south-1" }
variable "image_uri"    { type = string  default = "" } # set by deploy.sh after ECR push
variable "vpc_cidr"     { type = string  default = "10.20.0.0/16" }
