# /api/providers.py
import os
import requests
import json

HF_ENDPOINT = "https://api-inference.huggingface.co/models"
FW_ENDPOINT = "https://api.fireworks.ai/infer"  # Correct endpoint for completions

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