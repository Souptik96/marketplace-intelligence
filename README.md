Here's the updated README with the cost section added:

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

🚀 **Try it now**: [Hugging Face Space Demo](https://huggingface.co/spaces/soupstick/marketplace-intelligence  )

### The HF Space runs a simplified Gradio interface for quick testing. For the full FastAPI backend and AWS deployment, use this repository.
---
AWS Diagram:
<img width="10970" height="10175" alt="AWS Architecture" src="https://github.com/user-attachments/assets/ed191490-e37e-4143-9933-dfa595e2246b  " />
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
## Cost Section

> These are **ballpark** monthly estimates with typical current rates in common AWS regions. Replace with your exact region via AWS Pricing Calculator if you want precise numbers. The formulas below are what matter during reviews.

### Scenario A — **Low-cost dev**

| Component                                                  | Assumption                       |                   Formula |    Est. / mo |
| ---------------------------------------------------------- | -------------------------------- | ------------------------: | -----------: |
| **Fargate task**                                           | 0.5 vCPU, 1 GB RAM, 1 task, 24×7 | vCPU-hr×rate + GB-hr×rate |  ~\$18–\$25 |
| **ALB**                                                    | 1 LCU, 24×7 low traffic          |           ALB-hr + LCU-hr |  ~\$20–\$30 |
| **ECR**                                                    | 1 image, ~1 GB                  |                 GB×\$0.10 |     ~\$0.10 |
| **CloudWatch Logs**                                        | 1–2 GB / mo                      |                 GB×\$0.50 | ~\$0.50–\$1 |
| **Data transfer**                                          | negligible dev                   |                         — |        ~\$0 |
| **Total**: **~\$40–\$60 / month** (region variance ±15%). |                                  |                           |              |

> Why not "just one EC2"? Fargate keeps it serverless, removes patching, and is the default internal pattern for containerized microservices behind an ALB.

### Scenario B — **Full-scale pattern** (adds data services)

Assuming a moderate team workload:

* **Athena**: 2 TB scanned / mo → `$5/TB × 2` = **\$10** (with partitioning/Parquet).
* **S3 data lake**: 200 GB @ \$0.023/GB = **\$4.6** storage; **\$0.5–\$2** requests.
* **Glue**: 1 DPU × 1 hr/day × 30 days @ ~\$0.44/DPU-hr = **\$13**.
* **OpenSearch (vector)**: If you choose **Serverless**, the baseline can be **hundreds** per month (multiple OCUs always on). A cost-optimized alternative for demos is a **t3.small.search** single-AZ domain (~**\$35–\$60/mo**), trading off HA.
* **Kinesis Firehose (optional)**: 50 GB/mo ingest → **low single-digit \$**.

**Add** these to Scenario A: you're roughly **\$100–\$300+/mo** depending on OpenSearch choice and query volume.

### Cost levers to call out in README

* Parquet + partitioning (by `day`, `category`) to keep Athena \$/TB low.
* Turn off ALB + ECS when idle (`terraform destroy`) or scale task count to 0.
* For vectors: start with **OpenSearch small domain** or even **FAISS inside ECS** for zero baseline, then graduate to Serverless when traffic requires it.

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
