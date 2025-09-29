# /api/providers.py
import os
import requests
import json

HF_ENDPOINT = "https://api-inference.huggingface.co/models"
FW_ENDPOINT = "https://api.fireworks.ai/infer"  # Correct endpoint for completions

def extract_sql(text: str) -> str:
    """Pull SQL out of LLM text: prefer ```sql fences```, else first SELECT/WITH."""
    m = re.search(r"```sql\s*(.*?)```", text, flags=re.I | re.S)
    if m: return m.group(1).strip().rstrip(";")
    m = re.search(r"```(.*?)```", text, flags=re.S)
    if m: text = m.group(1)
    m = re.search(r"(?is)\b(select|with)\b.*", text)
    return m.group(0).strip() if m else text.strip()

def extract_json(text: str):
    """Best-effort JSON extraction from LLM output."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    blob = m.group(1) if m else text
    m = re.search(r"\{.*\}", blob, flags=re.S)
    blob = m.group(0) if m else blob
    try:
        return json.loads(blob)
    except Exception:
        return {"raw": text}

def _hf_call(model, prompt):
    response = requests.post(
        f"{HF_ENDPOINT}/{model}",
        headers={
            "Authorization": f"Bearer {os.getenv('HF_API_KEY', '')}",
        },
        json={"inputs": prompt, "parameters": {"max_new_tokens": 512, "temperature": 0.1}}
    )
    response.raise_for_status()
    json_resp = response.json()
    return json_resp[0]["generated_text"] if isinstance(json_resp, list) else json_resp["generated_text"]

def _fw_call(model, prompt):
    response = requests.post(
        FW_ENDPOINT,
        headers={
            "Authorization": f"Bearer {os.getenv('FIREWORKS_API_KEY', '')}",
            "Content-Type": "application/json"
        },
        json={
            "model": model,
            "prompt": prompt,  # Use 'prompt' for completion-style (your SQL gen/review fits)
            "max_generated_tokens": 512,
            "temperature": 0.1
        }
    )
    response.raise_for_status()
    result = response.json()
    # Parse response: Fireworks returns {"results": [{"text": "..."}]}
    if "results" in result and len(result["results"]) > 0:
        return result["results"][0]["text"]
    raise ValueError(f"Unexpected Fireworks response: {json.dumps(result)}")

def llm_call(kind, prompt):
    provider = os.getenv("LLM_PROVIDER", "hf")
    model = os.getenv("LLM_MODEL_GEN" if kind == "gen" else "LLM_MODEL_REV")
    if provider == "hf":
        return _hf_call(model, prompt)
    return _fw_call(model, prompt)