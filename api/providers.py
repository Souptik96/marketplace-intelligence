import os, json, requests

HF_BASE = "https://api-inference.huggingface.co/models"
FW_CHAT = "https://api.fireworks.ai/inference/v1/chat/completions"
FW_COMP = "https://api.fireworks.ai/inference/v1/completions"

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
    if isinstance(j, list) and j and "generated_text" in j[0]: return j[0]["generated_text"]
    if isinstance(j, dict) and "generated_text" in j: return j["generated_text"]
    return json.dumps(j)

def _fw_call(model: str, prompt: str) -> str:
    key = os.getenv("FIREWORKS_API_KEY", "")
    if not key:
        raise RuntimeError("FIREWORKS_API_KEY not set")
    h = {"Authorization": f"Bearer {key}"}
    # primary: chat/completions
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0, "max_tokens": 256}
    r = requests.post(FW_CHAT, headers=h, json=payload, timeout=60)
    if r.status_code == 404:
        # fallback: plain completions
        payload = {"model": model, "prompt": prompt, "temperature": 0, "max_tokens": 256}
        r = requests.post(FW_COMP, headers=h, json=payload, timeout=60)
    if r.status_code == 403:
        raise RuntimeError("Fireworks 403 Forbidden: invalid API key or no access to model. "
                           "Verify FIREWORKS_API_KEY and model id.")
    r.raise_for_status()
    j = r.json()
    # normalize
    if "choices" in j and j["choices"]:
        c = j["choices"][0]
        if "message" in c and "content" in c["message"]: return c["message"]["content"]
        if "text" in c: return c["text"]
    return json.dumps(j)

def llm_call(kind: str, prompt: str) -> str:
    prov = os.getenv("LLM_PROVIDER", "hf").lower()
    model = os.getenv("LLM_MODEL_GEN") if kind == "gen" else os.getenv("LLM_MODEL_REV")
    if not model:
        raise RuntimeError(f"Missing model id for kind={kind}. Set LLM_MODEL_GEN/REV.")
    try:
        return _hf_call(model, prompt) if prov == "hf" else _fw_call(model, prompt)
    except Exception as e:
        # graceful fallback to HF if Fireworks fails and HF key is present
        if prov != "hf" and os.getenv("HF_API_KEY"):
            return _hf_call(model, prompt)
        raise