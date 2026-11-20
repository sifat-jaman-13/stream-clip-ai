"""Transcript-based viral moment scoring for local and hosted AI providers."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request


class AIProviderError(RuntimeError):
    def __init__(self, message, *, quota=False):
        super().__init__(message)
        self.quota = quota


def _json_request(url, payload=None, headers=None, timeout=90):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"} if data is not None else {}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers,
                                     method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1200]
        quota = exc.code == 429 or any(term in detail.lower() for term in
                                       ("quota", "rate limit", "resource_exhausted", "billing"))
        raise AIProviderError(f"HTTP {exc.code}: {detail or exc.reason}", quota=quota) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(str(exc)) from exc


def ollama_models(base_url="http://127.0.0.1:11434"):
    base = base_url.rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise AIProviderError("Ollama URL must point to this computer (localhost).")
    data = _json_request(base + "/api/tags", timeout=5)
    return [str(model.get("name", "")) for model in data.get("models", []) if model.get("name")]


def _transcript(words, duration):
    return "\n".join(f"{max(0, int(start))}s: {text}" for start, _end, text in words
                     if text and 0 <= float(start) < duration)[:24000]


def _prompt(words, duration):
    return ("Find up to 12 short-form video highlights in this timestamped transcript. "
            "Favor surprising, funny, emotional, high-energy, or self-contained moments. "
            "Return ONLY JSON: {\"moments\":[{\"time\":seconds,\"score\":0-100,\"reason\":short string}]}. "
            "The time must point inside the moment, not at its start. Do not invent dialogue.\n"
            f"Duration: {int(duration)} seconds\nTranscript:\n{_transcript(words, duration)}")


def _parse_moments(value, duration):
    if isinstance(value, dict):
        moments = value.get("moments", value.get("highlights", []))
    else:
        moments = value
    if isinstance(moments, str):
        moments = json.loads(moments)
        return _parse_moments(moments, duration)
    result = []
    if not isinstance(moments, list):
        raise AIProviderError("AI response did not include a moments list.")
    for item in moments:
        if not isinstance(item, dict):
            continue
        try:
            time_sec = float(item.get("time", item.get("timestamp")))
            score = float(item.get("score", 75))
        except (TypeError, ValueError):
            continue
        if 0 <= time_sec < duration:
            result.append((int(time_sec), max(0.0, min(100.0, score))))
    return result


def _extract_json(text):
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", str(text), flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AIProviderError("AI response did not contain valid JSON.")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise AIProviderError("AI response contained invalid JSON.") from exc


def _ollama(prompt, config):
    models = ollama_models(config.get("ollama_url", "http://127.0.0.1:11434"))
    model = str(config.get("ollama_model", "")).strip()
    if not models:
        raise AIProviderError("Ollama is reachable, but no models are installed. Install a model in Ollama first.")
    if not model or model not in models:
        model = models[0]
    base = config.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
    result = _json_request(base + "/api/generate", {
        "model": model, "prompt": prompt, "stream": False,
        "format": "json", "options": {"temperature": 0.2},
    }, timeout=240)
    return _extract_json(result.get("response", ""))


def _gemini(prompt, config):
    key = str(config.get("gemini_api_key", "")).strip()
    model = str(config.get("gemini_model", "gemini-2.0-flash")).strip()
    if not key:
        raise AIProviderError("Add a Gemini API key in AI settings.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='.-')}:generateContent"
    data = _json_request(url, {"contents": [{"parts": [{"text": prompt}]}],
                               "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}},
                         headers={"Content-Type": "application/json", "x-goog-api-key": key}, timeout=90)
    try:
        return _extract_json(data["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError) as exc:
        detail = json.dumps(data.get("promptFeedback", data))[:500]
        raise AIProviderError("Gemini returned no highlight response: " + detail) from exc


def _huggingface(prompt, config):
    token = str(config.get("huggingface_token", "")).strip()
    model = str(config.get("huggingface_model", "Qwen/Qwen2.5-7B-Instruct")).strip()
    if not token:
        raise AIProviderError("Add a Hugging Face access token in AI settings to use hosted models.")
    data = _json_request("https://router.huggingface.co/v1/chat/completions", {
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2, "max_tokens": 1200,
    }, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, timeout=120)
    try:
        return _extract_json(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError("Hugging Face returned no highlight response.") from exc


def select_moments(provider, words, duration, config, log=lambda _message: None):
    """Return timestamp/score picks; Gemini quota exhaustion falls back to Ollama."""
    if provider == "hooks":
        return None
    prompt = _prompt(words, duration)
    backend = {"ollama": _ollama, "gemini": _gemini, "huggingface": _huggingface}.get(provider)
    if backend is None:
        raise AIProviderError("Unknown highlight provider.")
    try:
        raw = backend(prompt, config)
    except AIProviderError as exc:
        if provider != "gemini" or not exc.quota:
            raise
        log("Gemini quota/rate limit reached. Checking local Ollama for automatic fallback.")
        try:
            raw = _ollama(prompt, config)
        except AIProviderError as fallback_error:
            raise AIProviderError(f"Gemini quota is exhausted; Ollama fallback failed: {fallback_error}", quota=True) from fallback_error
        log("Gemini quota reached; highlight analysis completed with Ollama.")
    return _parse_moments(raw, duration)
