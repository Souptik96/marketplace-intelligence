import os, json, re, requests

# Providers
HF_BASE  = "https://api-inference.huggingface.co/models"  # Fixed trailing spaces
FW_CHAT  = "https://api.fireworks.ai/inference/v1/chat/completions"  # Fixed trailing spaces
FW_COMP  = "https://api.fireworks.ai/inference/v1/completions"  # Fixed trailing spaces

# ---------- Helper extractors (now live here so main.py can import them) ----------

def extract_sql(text: str) -> str:
    """Prefer ```sql ...``` fenced blocks, else first SELECT/WITH clause."""
    # 1. Try to extract from ```sql ... ``` blocks
    m = re.search(r"```sql\s*(.*?)```", text, flags=re.I | re.S)
    if m: 
        return m.group(1).strip().rstrip(";")
    
    # 2. If no specific sql block, try generic code blocks (might contain SQL)
    m = re.search(r"```(.*?)```", text, flags=re.S)
    if m: 
        potential_sql = m.group(1).strip()
        # Check if the content inside generic block looks like SQL
        if re.search(r"(?is)\b(select|from|with|insert|update|delete)\b", potential_sql):
            return potential_sql.rstrip(";")
    
    # 3. Fallback: Extract first SQL statement from plain text
    m = re.search(r"(?is)\b(select|with)\b.*?(?:;|$)", text)
    if m:
        sql = m.group(0).strip()
        # Ensure it ends with a complete clause, not mid-sentence
        # This finds the last major SQL clause keyword and cuts off after it if incomplete
        # For now, just return the matched SQL statement
        return sql.rstrip(";")
    
    # 4. If no SQL pattern found, return empty string or raise an error
    # Previously, it returned the entire text which could be non-SQL
    return ""  # Or raise ValueError("No SQL statement found in response")


def extract_json(text: str):
    """Best-effort JSON extraction from an LLM response."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    blob = m.group(1) if m else text
    m = re.search(r"\{.*\}", blob, flags=re.S)
    blob = m.group(0) if m else blob
    try:
        return json.loads(blob)
    except Exception:
        return {"raw": text}

# ---------- Provider calls ----------

def _hf_call(model: str, prompt: str) -> str:
    key = os.getenv("HF_API_KEY", "")
    if not key:
        raise RuntimeError("HF_API_KEY not set")
    r = requests.post(
        f"{HF_BASE}/{model}",
        headers={"Authorization": f"Bearer {key}", "x-use-cache": "false"},
        json={"inputs": prompt, "parameters": {"max_new_tokens": 256, "temperature": 0}},
        timeout=60,
    )
    r.raise_for_status()
    j = r.json()
    if isinstance(j, list) and j and "generated_text" in j[0]:
        return j[0]["generated_text"]
    if isinstance(j, dict) and "generated_text" in j:
        return j["generated_text"]
    return json.dumps(j)

def _fw_call(model: str, prompt: str) -> str:
    key = os.getenv("FIREWORKS_API_KEY", "")
    if not key:
        raise RuntimeError("FIREWORKS_API_KEY not set")
    h = {"Authorization": f"Bearer {key}"}

    # Primary: chat/completions
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0, "max_tokens": 256}
    r = requests.post(FW_CHAT, headers=h, json=payload, timeout=60)

    # Fallback: plain completions
    if r.status_code == 404:
        payload = {"model": model, "prompt": prompt, "temperature": 0, "max_tokens": 256}
        r = requests.post(FW_COMP, headers=h, json=payload, timeout=60)

    if r.status_code == 403:
        raise RuntimeError("Fireworks 403 Forbidden: invalid API key or no access to the model id.")

    r.raise_for_status()
    j = r.json()
    if "choices" in j and j["choices"]:
        c = j["choices"][0]
        if "message" in c and "content" in c["message"]:
            return c["message"]["content"]
        if "text" in c:
            return c["text"]
    return json.dumps(j)

def llm_call(kind: str, prompt: str) -> str:
    """kind: 'gen' or 'rev' — picks model via env vars."""
    prov  = os.getenv("LLM_PROVIDER", "hf").lower()
    model = os.getenv("LLM_MODEL_GEN") if kind == "gen" else os.getenv("LLM_MODEL_REV")
    if not model:
        raise RuntimeError(f"Missing model id for kind={kind}. Set LLM_MODEL_GEN/REV.")
    try:
        return _hf_call(model, prompt) if prov == "hf" else _fw_call(model, prompt)
    except Exception as e:
        # If Fireworks fails and HF is available, auto-fallback
        if prov != "hf" and os.getenv("HF_API_KEY"):
            return _hf_call(model, prompt)
        raise