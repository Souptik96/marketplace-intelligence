variable "project_name"   { type = string  default = "bizsql" }
variable "region"         { type = string  default = "ap-south-1" }
variable "image_uri"      { type = string  default = "" } # set by deploy.sh
variable "vpc_cidr"       { type = string  default = "10.20.0.0/16" }

# LLM config for task env
variable "llm_provider"   { type = string  default = "hf" }
variable "llm_model_gen"  { type = string  default = "Qwen/Qwen2.5-1.5B-Instruct" }
variable "llm_model_rev"  { type = string  default = "Qwen/Qwen2.5-Coder-1.5B-Instruct" }
variable "hf_api_key"     { type = string  default = "" }
variable "fireworks_api_key" { type = string default = "" }