import os, json, re, requests

HF_BASE = "https://api-inference.huggingface.co/models"
FW_BASE = "https://api.fireworks.ai/inference/v1/chat/completions"

def _hf_call(model: str, prompt: str) -> str:
    headers = {"Authorization": f"Bearer {os.getenv('HF_API_KEY','')}",
               "x-use-cache": "false"}
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": 256, "temperature": 0}}
    r = requests.post(f"{HF_BASE}/{model}", headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    j = r.json()
    # different models return list/dict; normalize
    if isinstance(j, list) and j and "generated_text" in j[0]:
        return j[0]["generated_text"]
    if isinstance(j, dict) and "generated_text" in j:
        return j["generated_text"]
    # fallback: try 'data' shape
    return json.dumps(j)

def _fw_call(model: str, prompt: str) -> str:
    headers = {"Authorization": f"Bearer {os.getenv('FIREWORKS_API_KEY','')}"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0, "max_tokens": 256}
    r = requests.post(FW_BASE, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"]

def llm_call(kind: str, prompt: str) -> str:
    prov = os.getenv("LLM_PROVIDER", "hf").lower()
    model = os.getenv("LLM_MODEL_GEN") if kind == "gen" else os.getenv("LLM_MODEL_REV")
    if not model:
        raise RuntimeError(f"Missing model id for kind={kind}. Set LLM_MODEL_GEN/REV.")
    txt = _hf_call(model, prompt) if prov == "hf" else _fw_call(model, prompt)
    return txt

def extract_sql(text: str) -> str:
    m = re.search(r"```sql\s*(.*?)```", text, flags=re.I | re.S)
    if m: return m.group(1).strip().rstrip(";")
    m = re.search(r"```(.*?)```", text, flags=re.S)
    if m: text = m.group(1)
    m = re.search(r"(?is)\b(select|with)\b.*", text)
    return m.group(0).strip() if m else text.strip()

def extract_json(text: str):
    # try fenced
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    blob = m.group(1) if m else text
    # locate first {...}
    m = re.search(r"\{.*\}", blob, flags=re.S)
    blob = m.group(0) if m else blob
    try: return json.loads(blob)
    except: return {"raw": text}