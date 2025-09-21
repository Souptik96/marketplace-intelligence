# Marketplace Intelligence & GenAI Product Analyst — One‑Click AWS (ECS Fargate)

**What it is**: Production‑style demo for NL→SQL over marketplace sales.
- **Local**: DuckDB + FastAPI.
- **Cloud**: One click to **AWS ECS Fargate** with ALB, ECR, VPC via **Terraform**.

---
## Quick Start (Local)
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python data/synthetic_generator.py                   # builds data/out/market.duckdb
uvicorn api.main:app --host 0.0.0.0 --port 8000
# Test:
curl http://localhost:8000/health
curl "http://localhost:8000/ask?q=Top%203%20selling%20electronics%20products%20in%20Q3"
```

Optional UI (local only):

```bash
pip install streamlit
streamlit run app/streamlit_app.py
```

---
## Live Demo

🚀 **Try it now**: [Hugging Face Space Demo](https://huggingface.co/spaces/soupstick/marketplace-intelligence)

### The HF Space runs a simplified Gradio interface for quick testing. For the full FastAPI backend and AWS deployment, use this repository.
---
AWS Diagram:
<img width="10970" height="10175" alt="AWS Architecture" src="https://github.com/user-attachments/assets/ed191490-e37e-4143-9933-dfa595e2246b" />
---
## One‑Click Deploy to AWS (ECS Fargate)

**Prereqs**: AWS CLI configured with deploy permissions, Docker, Terraform ≥ 1.7.

```bash
chmod +x deploy.sh
./deploy.sh
```

What `deploy.sh` does:

1. Creates **ECR** repo.
2. Builds the API container (bakes DuckDB data) and pushes to ECR.
3. Provisions **VPC, Subnets, IGW, ALB, ECS Fargate Service**, CW Logs.
4. Prints your **ALB URL**. Endpoints:

   * `http://<alb>/health`
   * `http://<alb>/ask?q=Top%203%20selling%20electronics%20products%20in%20Q3`

> Default runtime queries the baked DuckDB so it's usable immediately. To migrate to Athena later, switch `APP_ENV=aws` and implement the existing `query_athena()` stub.

---

## Repo Layout

```
api/                 FastAPI service (NL→SQL + DuckDB)
app/streamlit_app.py Optional local UI
data/synthetic_generator.py  Synthetic dataset builder
terraform/           ECS + ALB + VPC + ECR (Terraform)
Dockerfile.api       API image build (includes data)
deploy.sh            One‑click: build, push, terraform apply
requirements.txt
```

---

## Clean‑up

```bash
terraform -chdir=terraform destroy -auto-approve
```
