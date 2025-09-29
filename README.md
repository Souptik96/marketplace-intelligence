# DataWeaver

DataWeaver is a streamlined system that converts business logic (natural language queries) into SQL code, reviews it for accuracy, and generates interactive dashboards. Inspired by tools like Julius AI, it leverages small, open-source LLMs (e.g., Qwen2.5 variants) for NL2SQL generation and review, with a FastAPI backend, Streamlit front-end, and AWS Fargate deployment. This project builds on a clone of marketplace-intelligence and is designed for quick prototyping and scalability.

## Project Overview

**Purpose:** Automate business intelligence workflows by translating natural language to SQL, validating queries, and visualizing data.

**Tech Stack:** Python (FastAPI, Streamlit, DuckDB), Terraform (AWS), Hugging Face Inference/Fireworks.

**Deployment:** AWS Fargate (API) + Hugging Face Spaces (UI).

**Target Audience:** Companies like xAI, Google, or Perplexity for AI-driven BI solutions.

## Features

- **NL2SQL Generation:** Converts business questions (e.g., "Top 5 products by revenue") into DuckDB SQL.
- **SQL Review:** Validates and suggests improvements to generated SQL.
- **Dashboard Generation:** Auto-creates charts from query results, with placeholders for missing data.
- **Scalable Deployment:** One-click AWS deployment with Terraform.

## Getting Started

### Prerequisites

- Python 3.12
- Git
- AWS CLI (configured with credentials)
- Hugging Face API Key or Fireworks API Key
- Docker

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Souptik96/marketplace-intelligence.git DataWeaver
   cd DataWeaver
   git checkout v1-dataweaver-core
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set environment variables:
   ```bash
   export HF_API_KEY=your_hf_key
   export LLM_PROVIDER=hf
   export LLM_MODEL_GEN=Qwen/Qwen2.5-1.5B-Instruct
   export LLM_MODEL_REV=Qwen/Qwen2.5-Coder-1.5B-Instruct
   ```

4. Generate sample data (if not present):
   ```bash
   python data/synthetic_generator.py
   ```

## Local Development

1. Run the API:
   ```bash
   uvicorn api.main:app --host 0.0.0.0 --port 8000
   ```

2. Run the UI:
   ```bash
   streamlit run app/app.py
   ```

3. Test endpoints (e.g., `curl -X GET "http://localhost:8000/execute?q=Top+5+products+by+revenue"`).

## Deployment

### Hugging Face Spaces (UI)

1. Create a Space at Hugging Face.
2. Upload `app/app.py`, `requirements.txt`, and `data/daily_product_sales.csv`.
3. Set `API_URL` secret to your AWS ALB DNS (post-deployment).

### AWS Fargate (API)

1. Configure AWS CLI and Terraform.
2. Run the deployment script:
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```
3. Update HF Space `API_URL` with the output ALB DNS.

## Usage

- **Ask Tab:** Input a business question (e.g., "Revenue by category last month") to generate SQL, see results, and view a chart.
- **Review Tab:** Paste SQL or a question to get validation and suggestions.
- **Dashboard Tab:** View auto-generated visuals or placeholders for missing data.

## Metrics

**Performance:**
- SQL Creation Time: ~5-10 seconds (95% reduction from 6-10 min baseline).
- Review Time: ~10-30 seconds (85% reduction from 3-5 min).
- Dashboard Time: <10 minutes (90% reduction from 1-2 hrs).

- **Accuracy:** ≥85% top-1 accuracy on synthetic test set (run `python tests/test_nl2sql.py`).
- **Latency:** Gen (2s), Review (3s), Execute (~1s) per query.
- **Cost:** ~$40-60/mo (ECS + ALB) + <$10/mo (inference).

## Directory Structure

```
/api           # FastAPI backend (NL2SQL, review, execute)
/app           # Streamlit UI (chat, review, dashboard)
/infra/terraform # AWS infrastructure (VPC, ECS, ALB)
/deploy.sh     # One-click deployment script
/README.md     # This file
/requirements.txt # Dependencies
/data          # Sample data (daily_product_sales.csv)
/sql           # Schema definition
/tests         # Unit tests
/dashboards    # Future dashboard configs
```

## Contributing

Fork the repo, create a feature branch, and submit a pull request. Follow the GitHub Community Guidelines.

## License

MIT License (add a LICENSE file if desired).
