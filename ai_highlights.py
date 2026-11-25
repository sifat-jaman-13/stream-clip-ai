"""Transcript-based viral moment scoring for local and hosted AI providers."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import queue
import threading
import hashlib
import time

_GEMINI_MODEL_CACHE = {}
_GEMINI_ACTIVE_CACHE = {}
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
RETIRED_GEMINI_MODELS = {"gemini-2.5-flash"}
GEMINI_ATTEMPTS_PER_MODEL = 3
GEMINI_ROTATION_ROUNDS = 2
DEFAULT_HUGGINGFACE_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash:fastest"


class AIProviderError(RuntimeError):
    def __init__(self, message, *, quota=False, retryable=False):
        super().__init__(message)
        self.quota = quota
        self.retryable = retryable


class AIAnalysisCancelled(RuntimeError):
    pass


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
        model_specific = any(term in detail.lower() for term in
                             ("model", "not supported", "unsupported", "unavailable", "responsemimetype"))
        retryable = quota or exc.code in {404, 408, 429, 500, 502, 503, 504} or (exc.code == 400 and model_specific)
        raise AIProviderError(f"HTTP {exc.code}: {detail or exc.reason}", quota=quota,
                              retryable=retryable) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(str(exc), retryable=True) from exc


def ollama_models(base_url="http://127.0.0.1:11434"):
    base = base_url.rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}:
        raise AIProviderError("Ollama URL must point to this computer (localhost or host.docker.internal in Docker).")
    data = _json_request(base + "/api/tags", timeout=5)
    return [str(model.get("name", "")) for model in data.get("models", []) if model.get("name")]


def _transcript(words, duration):
    # Group rapid word timestamps into readable five-second lines to keep prompts compact.
    buckets = {}
    for start, _end, text in words:
        if text and 0 <= float(start) < duration:
            bucket = max(0, int(float(start) // 5) * 5)
            buckets.setdefault(bucket, []).append(str(text).strip())
    return "\n".join(f"{second}s: {' '.join(tokens)}" for second, tokens in sorted(buckets.items()))


def _prompt(words, duration):
    return ("Act as a human short-form viral editor, not a literal keyword filter. Find up to 8 "
            "plausible highlights in this timestamped transcript window and score each one honestly. "
            "Consider emotional intensity, shock, absurdity, dark humor, irony, escalating stakes, "
            "conflict, risky decisions, a strong question, a surprising reveal, a memorable quote, "
            "or a big reaction. Streamer/gameplay moments can be viral even when the transcript does "
            "not contain the final visual payoff. Profanity counts only when it communicates real "
            "emotion or makes the situation funnier; do not reward profanity by itself. "
            "Use this human-style 0-100 scale: 50 = ordinary context, 60 = mildly interesting, "
            "70 = clear emotional/absurd/story beat, 80 = strong clip candidate likely to hold a "
            "cold viewer, 90 = exceptional shareable moment, 100 = undeniable standout. "
            "Return strong candidates even when they score below 80; the app applies the user's final "
            "viral-score threshold. Returning no moments is appropriate only when the window is truly "
            "flat or unintelligible. Return ONLY JSON: {\"moments\":[{\"time\":seconds,\"score\":0-100,\"reason\":short string}]}. "
            "The reason must explain the emotion, absurdity, stakes, irony, escalation, or quote that "
            "makes the moment interesting. The time must point inside the beat, not at its start. "
            "Do not invent dialogue or claim an event that is not supported by the transcript.\n"
            f"Duration: {int(duration)} seconds\nTranscript:\n{_transcript(words, duration)}")


def _parse_moments(value, duration):
    if isinstance(value, dict):
        moments = value.get("moments", value.get("highlights", []))
    else:
        moments = value
    if isinstance(moments, str):
        try:
            moments = json.loads(moments)
        except json.JSONDecodeError as exc:
            raise AIProviderError("AI response contained an invalid moments JSON string.") from exc
        return _parse_moments(moments, duration)
    result = []
    if not isinstance(moments, list):
        raise AIProviderError("AI response did not include a moments list.")
    for item in moments:
        if not isinstance(item, dict):
            continue
        try:
            time_sec = float(item.get("time", item.get("timestamp")))
            # A missing score used to silently become 75, which let arbitrary model
            # suggestions clear a user's 70-point floor. A provider must now make
            # an explicit, auditable confidence claim for every proposed moment.
            if "score" not in item:
                continue
            score = float(item["score"])
        except (TypeError, ValueError):
            continue
        if 0 <= time_sec < duration:
            result.append((int(time_sec), max(0.0, min(100.0, score))))
    return result


def _transcript_engagement(words, second):
    """Return a conservative 0-100 engagement signal around an AI-proposed time.

    LLM scores are not calibrated probabilities. This intentionally modest signal
    prevents a generic sentence that a model labels 70-80 from passing the same
    floor as a moment with an audible reaction, punchline, or rapid exchange.
    """
    nearby = [str(text).strip() for start, _end, text in words
              if abs(float(start) - float(second)) <= 12 and str(text).strip()]
    if not nearby:
        return 0.0
    text = " ".join(nearby)
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    # Normal spoken commentary stays near the floor; the signal rises only with
    # an actual reaction, payoff language, expressive punctuation, or rapid talk.
    density = min(24.0, len(tokens) * 1.2)
    reaction_terms = {
        "wow", "whoa", "no", "way", "insane", "crazy", "unbelievable", "clutch",
        "lets", "go", "holy", "god", "damn", "what", "happened", "killed", "win",
        "won", "lost", "impossible", "perfect", "fail", "funny", "laugh", "cry",
    }
    reactions = sum(token in reaction_terms for token in tokens)
    reaction = min(42.0, reactions * 7.0)
    expressive = min(14.0, text.count("!") * 7.0 + text.count("?") * 3.0)
    variety = min(10.0, len(set(tokens)) / max(1, len(tokens)) * 10.0)
    return min(100.0, 12.0 + density + reaction + expressive + variety)


def _calibrate_score(model_score, words, second):
    """Blend an LLM's subjective score with transcript evidence conservatively."""
    evidence = _transcript_engagement(words, second)
    # The model's contextual judgment is primary; transcript evidence is a
    # light calibration signal so expressive moments are not crushed merely
    # because ASR missed the visual payoff or reaction.
    return round(max(0.0, min(100.0, 0.9 * float(model_score) + 0.1 * evidence)), 1)


def _extract_json(text):
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", str(text), flags=re.I)
    starts = [pos for pos in (text.find("{"), text.find("[")) if pos >= 0]
    if not starts:
        raise AIProviderError("AI response did not contain valid JSON.")
    decoder = json.JSONDecoder()
    try:
        value, _end = decoder.raw_decode(text[min(starts):].lstrip())
        if not isinstance(value, (dict, list)):
            raise ValueError("JSON root must be an object or array")
        return value
    except (json.JSONDecodeError, ValueError) as exc:
        raise AIProviderError("AI response contained invalid JSON.") from exc


def _ollama(prompt, config):
    models = ollama_models(config.get("ollama_url", "http://127.0.0.1:11434"))
    model = str(config.get("ollama_model", "")).strip()
    if not models:
        raise AIProviderError("Ollama is reachable, but no models are installed. Install a model in Ollama first.")
    if not model or model not in models:
        model = models[0]
    base = config.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
    if config.get("_ollama_logged_model") != model:
        report = config.get("_ai_log")
        if callable(report):
            report(f"Ollama local model: {model} at {base} (runs on this computer).")
        config["_ollama_logged_model"] = model
    report = config.get("_ai_log")
    if callable(report):
        start, end = config.get("_ai_window", (0, 0))
        report(f"Running Ollama local model {model} on {base}; analyzing transcript window {int(start)}–{int(end)}s.")
    result = _json_request(base + "/api/generate", {
        "model": model, "prompt": prompt, "stream": False,
        "format": "json", "options": {"temperature": 0.2, "num_ctx": 8192},
    }, timeout=240)
    parsed = _extract_json(result.get("response", ""))
    report = config.get("_ai_log")
    if callable(report):
        start, end = config.get("_ai_window", (0, 0))
        count = len(parsed.get("moments", [])) if isinstance(parsed, dict) and isinstance(parsed.get("moments", []), list) else 0
        report(f"Ollama local model {model} analyzed transcript window {int(start)}–{int(end)}s and returned {count} moments.")
    return parsed


def _gemini_available_models(key):
    """Return all Gemini models exposed by this key that support generateContent."""
    names = []
    page_token = ""
    seen_tokens = set()
    for _ in range(100):
        query = urllib.parse.urlencode({"pageSize": 1000, **({"pageToken": page_token} if page_token else {})})
        data = _json_request("https://generativelanguage.googleapis.com/v1beta/models?" + query,
                             headers={"x-goog-api-key": key}, timeout=20)
        for item in data.get("models", []):
            name = str(item.get("name", ""))
            methods = item.get("supportedGenerationMethods", [])
            model = name.removeprefix("models/")
            lower = model.lower()
            unsuitable = model in RETIRED_GEMINI_MODELS or any(term in lower for term in (
                "image", "tts", "embedding", "vision", "robotics", "live",
                "native-audio", "computer-use",
            ))
            if model.startswith("gemini-") and "generateContent" in methods and not unsuitable:
                names.append(model)
        page_token = str(data.get("nextPageToken", ""))
        if not page_token or page_token in seen_tokens:
            break
        seen_tokens.add(page_token)
    names = list(dict.fromkeys(names))

    def priority(model):
        lower = model.lower()
        if model == DEFAULT_GEMINI_MODEL:
            return 0
        if "flash-lite" in lower:
            return 3
        if "flash" in lower:
            return 1
        if "pro" in lower:
            return 2
        return 4

    names.sort(key=lambda model: (priority(model), model))
    return names


def _gemini_model_order(selected, available=()):
    """Prefer the configured model, replacing known retired IDs with the current default."""
    selected = str(selected or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    if selected in RETIRED_GEMINI_MODELS:
        selected = DEFAULT_GEMINI_MODEL
    return list(dict.fromkeys(
        model for model in [selected, DEFAULT_GEMINI_MODEL, *available]
        if model and model not in RETIRED_GEMINI_MODELS
    ))


def _gemini(prompt, config):
    key = str(config.get("gemini_api_key", "")).strip()
    selected = str(config.get("gemini_model", DEFAULT_GEMINI_MODEL)).strip()
    selected = _gemini_model_order(selected)[0]
    if not key:
        raise AIProviderError("Add a Gemini API key in AI settings.")
    cache_id = hashlib.sha256(key.encode("utf-8")).hexdigest()
    cached_models = config.get("_gemini_fallback_models")
    if cached_models is None:
        try:
            cached_models = _gemini_available_models(key)
        except AIProviderError as exc:
            if not exc.retryable:
                raise
            cached_models = _GEMINI_MODEL_CACHE.get(cache_id, [])
        config["_gemini_fallback_models"] = cached_models
        if len(_GEMINI_MODEL_CACHE) >= 8 and cache_id not in _GEMINI_MODEL_CACHE:
            _GEMINI_MODEL_CACHE.pop(next(iter(_GEMINI_MODEL_CACHE)))
        _GEMINI_MODEL_CACHE[cache_id] = cached_models
    active = str(config.get("_gemini_active_model", "")).strip()
    # Keep the last proven-working Gemini model sticky across separate analyses
    # (live windows, new clips, titles/descriptions, and monitoring jobs). A
    # manual model change resets this preference; a later failure rotates away.
    cached_choice = _GEMINI_ACTIVE_CACHE.get(cache_id)
    sticky_model = cached_choice[1] if cached_choice and cached_choice[0] == selected else ""
    models = list(dict.fromkeys(
        model for model in [sticky_model, active, selected, DEFAULT_GEMINI_MODEL, *(cached_models or [])]
        if model and model not in RETIRED_GEMINI_MODELS
    ))
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    last_error = None
    attempts = 0
    for rotation_round in range(1, GEMINI_ROTATION_ROUNDS + 1):
        for model_index, model in enumerate(models):
            for model_attempt in range(1, GEMINI_ATTEMPTS_PER_MODEL + 1):
                cancelled = config.get("_gemini_cancelled")
                if callable(cancelled) and cancelled():
                    raise AIAnalysisCancelled("AI highlight analysis stopped by user.")
                attempts += 1
                report = config.get("_ai_log")
                if callable(report):
                    start, end = config.get("_ai_window", (0, 0))
                    report(
                        f"Trying Gemini cloud model {model} (rotation {rotation_round}/{GEMINI_ROTATION_ROUNDS}, "
                        f"attempt {model_attempt}/{GEMINI_ATTEMPTS_PER_MODEL}) through Google's API "
                        f"for transcript window {int(start)}–{int(end)}s."
                    )
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='.-')}:generateContent"
                try:
                    data = _json_request(url, {"contents": [{"parts": [{"text": prompt}]}],
                                           "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}},
                                         headers=headers, timeout=45 if attempts == 1 else 30)
                    try:
                        result = _extract_json(data["candidates"][0]["content"]["parts"][0]["text"])
                    except (KeyError, IndexError, TypeError) as exc:
                        detail = json.dumps(data.get("promptFeedback", data))[:500]
                        raise AIProviderError("Gemini returned no highlight response: " + detail,
                                              retryable=True) from exc
                    config["_gemini_active_model"] = model
                    if len(_GEMINI_ACTIVE_CACHE) >= 8 and cache_id not in _GEMINI_ACTIVE_CACHE:
                        _GEMINI_ACTIVE_CACHE.pop(next(iter(_GEMINI_ACTIVE_CACHE)))
                    _GEMINI_ACTIVE_CACHE[cache_id] = (selected, model)
                    if model != selected:
                        config["_gemini_using_alternate"] = model
                    if callable(report):
                        start, end = config.get("_ai_window", (0, 0))
                        report(f"Gemini cloud model {model} analyzed transcript window {int(start)}–{int(end)}s using the Google Gemini API.")
                    return result
                except AIProviderError as exc:
                    last_error = exc
                    if "invalid JSON" in str(exc) or "did not contain valid JSON" in str(exc) or "no highlight response" in str(exc):
                        exc.retryable = True
                    if not exc.retryable:
                        raise
                    retry_log = config.get("_gemini_log")
                    if callable(retry_log):
                        if model_attempt < GEMINI_ATTEMPTS_PER_MODEL:
                            retry_log(f"Gemini model {model} failed ({str(exc)[:180]}). Staying on this model until its retries are exhausted.")
                        elif model_index + 1 < len(models):
                            retry_log(f"Gemini model {model} failed three times in rotation {rotation_round}. Switching to {models[model_index + 1]}.")
                    if model_attempt < GEMINI_ATTEMPTS_PER_MODEL:
                        time.sleep(0.4 * model_attempt)
        if rotation_round < GEMINI_ROTATION_ROUNDS and callable(config.get("_gemini_log")):
            config["_gemini_log"](
                f"Gemini rotation {rotation_round} exhausted all {len(models)} model(s); starting rotation {rotation_round + 1}."
            )
    if last_error:
        raise AIProviderError(
            f"Gemini model rotation failed after {attempts} attempts across {len(models)} model(s) "
            f"and {GEMINI_ROTATION_ROUNDS} rotation rounds; "
            f"each model was tried {GEMINI_ATTEMPTS_PER_MODEL} times. Last error: {last_error}",
            quota=last_error.quota, retryable=last_error.retryable) from last_error
    raise AIProviderError("No Gemini models supporting text generation are available for this API key.")


def _huggingface(prompt, config):
    token = str(config.get("huggingface_token", "")).strip()
    model = str(config.get("huggingface_model", DEFAULT_HUGGINGFACE_MODEL)).strip()
    if not token:
        raise AIProviderError("Add a Hugging Face access token in AI settings to use hosted models.")
    report = config.get("_ai_log")
    if callable(report):
        start, end = config.get("_ai_window", (0, 0))
        report(f"Running Hugging Face hosted model {model} through the Inference Providers router for transcript window {int(start)}–{int(end)}s.")
    data = _json_request("https://router.huggingface.co/v1/chat/completions", {
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2, "max_tokens": 1200,
    }, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, timeout=120)
    try:
        result = _extract_json(data["choices"][0]["message"]["content"])
        report = config.get("_ai_log")
        if callable(report):
            start, end = config.get("_ai_window", (0, 0))
            report(f"Hugging Face hosted model {model} analyzed transcript window {int(start)}–{int(end)}s through the Inference Providers router.")
        return result
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError("Hugging Face returned no highlight response.") from exc


def _openai_compatible(prompt, config):
    """Call any user-configured OpenAI-compatible chat-completions endpoint."""
    base = str(config.get("custom_api_base", "")).strip().rstrip("/")
    model = str(config.get("custom_api_model", "")).strip()
    key = str(config.get("custom_api_key", "")).strip()
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIProviderError("Enter a valid HTTP or HTTPS API base URL.")
    if not model:
        raise AIProviderError("Enter the model name for your OpenAI-compatible API.")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    report = config.get("_ai_log")
    if callable(report):
        start, end = config.get("_ai_window", (0, 0))
        report(f"Running custom OpenAI-compatible model {model} for transcript window {int(start)}–{int(end)}s.")
    data = _json_request(url, {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "stream": False,
    }, headers=headers, timeout=150)
    try:
        raw = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError("Custom API returned no chat-completions content.") from exc
    result = _extract_json(raw)
    if callable(report):
        start, end = config.get("_ai_window", (0, 0))
        count = len(result.get("moments", [])) if isinstance(result, dict) and isinstance(result.get("moments", []), list) else 0
        report(f"Custom OpenAI-compatible model {model} analyzed transcript window {int(start)}–{int(end)}s and returned {count} moments.")
    return result


def test_provider(provider, config):
    """Make a minimal authenticated request and return a secret-free status."""
    if provider == "hooks":
        return {"ok": True, "provider": "hooks", "model": "", "message": "Built-in hook scoring is ready."}
    if provider == "ollama":
        models = ollama_models(config.get("ollama_url", "http://127.0.0.1:11434"))
        if not models:
            raise AIProviderError("Ollama is reachable, but no models are installed.")
        selected = str(config.get("ollama_model", "")).strip()
        model = selected if selected in models else models[0]
        return {"ok": True, "provider": "ollama", "model": model,
                "message": f"Ollama is reachable and {model} is available."}
    if provider == "gemini":
        key = str(config.get("gemini_api_key", "")).strip()
        if not key:
            raise AIProviderError("Add a Gemini API key before testing the connection.")
        try:
            models = _gemini_available_models(key)
        except AIProviderError as exc:
            if any(code in str(exc) for code in ("HTTP 400", "HTTP 401", "HTTP 403")):
                raise AIProviderError(
                    "Gemini rejected this API key. Check that it is copied correctly and enabled for the Gemini API."
                ) from exc
            raise
        if not models:
            raise AIProviderError("The Gemini key is valid, but it exposes no text-generation models.")
        selected = str(config.get("gemini_model", DEFAULT_GEMINI_MODEL)).strip()
        candidates = _gemini_model_order(selected, models)
        last_error = None
        attempts = 0
        for model in candidates:
            for model_attempt in range(1, GEMINI_ATTEMPTS_PER_MODEL + 1):
                attempts += 1
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='.-')}:generateContent"
                try:
                    data = _json_request(url, {
                        "contents": [{"parts": [{"text": "Reply with exactly STREAMSNIP_OK."}]}],
                        "generationConfig": {"temperature": 0, "maxOutputTokens": 32},
                    }, headers={"Content-Type": "application/json", "x-goog-api-key": key}, timeout=45)
                    text = str(data["candidates"][0]["content"]["parts"][0]["text"]).strip()
                    if not text:
                        raise AIProviderError("Gemini accepted the key but returned an empty test response.",
                                              retryable=True)
                    return {"ok": True, "provider": "gemini", "model": model,
                            "attempts": attempts,
                            "message": f"Gemini API key works. Text generation succeeded with {model}."}
                except (KeyError, IndexError, TypeError) as exc:
                    last_error = AIProviderError("Gemini accepted the key but returned no test response.",
                                                 retryable=True)
                    last_error.__cause__ = exc
                except AIProviderError as exc:
                    last_error = exc
                    if not exc.retryable:
                        if any(code in str(exc) for code in ("HTTP 400", "HTTP 401", "HTTP 403")):
                            raise AIProviderError(
                                "Gemini rejected this API key. Check that it is copied correctly and enabled for the Gemini API."
                            ) from exc
                        raise
                if model_attempt < GEMINI_ATTEMPTS_PER_MODEL:
                    time.sleep(0.4 * model_attempt)
        if last_error and last_error.quota:
            raise AIProviderError(
                f"The Gemini key is valid, but quota or rate limits remained exhausted after {attempts} attempts "
                f"across {len(candidates)} model(s).", quota=True, retryable=True) from last_error
        raise AIProviderError(
            f"The Gemini key is valid, but generation failed after {attempts} attempts across "
            f"{len(candidates)} model(s); each model was tried {GEMINI_ATTEMPTS_PER_MODEL} times. "
            f"Last error: {last_error}", retryable=True) from last_error
    if provider == "huggingface":
        token = str(config.get("huggingface_token", "")).strip()
        model = str(config.get("huggingface_model", DEFAULT_HUGGINGFACE_MODEL)).strip() or DEFAULT_HUGGINGFACE_MODEL
        if not token:
            raise AIProviderError("Add a Hugging Face access token before testing the connection.")
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        try:
            _json_request("https://huggingface.co/api/whoami-v2",
                          headers={"Authorization": "Bearer " + token}, timeout=20)
        except AIProviderError as exc:
            if any(code in str(exc) for code in ("HTTP 401", "HTTP 403")):
                raise AIProviderError(
                    "Hugging Face rejected this token. Create a new token with Inference Providers access."
                ) from exc
            raise
        try:
            data = _json_request("https://router.huggingface.co/v1/chat/completions", {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly STREAMSNIP_OK."}],
                "temperature": 0,
                "max_tokens": 32,
                "stream": False,
            }, headers=headers, timeout=90)
        except AIProviderError as exc:
            detail = str(exc)
            if "HTTP 402" in detail:
                raise AIProviderError("The Hugging Face token works, but the account has no available provider credits.") from exc
            if any(code in detail for code in ("HTTP 400", "HTTP 404")):
                raise AIProviderError(f"Hugging Face could not run model '{model}'. Choose a currently available chat model.") from exc
            raise
        try:
            text = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("Hugging Face accepted the token but returned no test response.") from exc
        if not text:
            raise AIProviderError("Hugging Face accepted the token but returned an empty test response.")
        return {"ok": True, "provider": "huggingface", "model": model,
                "message": f"Hugging Face token works. Inference succeeded with {model}."}
    if provider == "custom":
        base = str(config.get("custom_api_base", "")).strip().rstrip("/")
        model = str(config.get("custom_api_model", "")).strip()
        key = str(config.get("custom_api_key", "")).strip()
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AIProviderError("Enter a valid HTTP or HTTPS API base URL.")
        if not model:
            raise AIProviderError("Enter the model name for your OpenAI-compatible API.")
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        try:
            data = _json_request(url, {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly STREAMSNIP_OK."}],
                "temperature": 0,
                "max_tokens": 32,
                "stream": False,
            }, headers=headers, timeout=90)
            response = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("Custom API returned no chat-completions response.") from exc
        if not response:
            raise AIProviderError("Custom API returned an empty test response.")
        return {"ok": True, "provider": "custom", "model": model,
                "message": f"Custom OpenAI-compatible API works. Model {model} responded."}
    raise AIProviderError("Unknown highlight provider.")


def _call_backend(backend, prompt, config, cancelled):
    if cancelled is None:
        return backend(prompt, config)
    result = queue.Queue(maxsize=1)
    def run():
        try: result.put((True, backend(prompt, config)))
        except Exception as exc: result.put((False, exc))
    threading.Thread(target=run, daemon=True, name="highlight-ai-request").start()
    while True:
        if cancelled():
            raise AIAnalysisCancelled("AI highlight analysis stopped by user.")
        try:
            ok, value = result.get(timeout=0.15)
            if ok: return value
            raise value
        except queue.Empty:
            continue


def select_moments(provider, words, duration, config, log=lambda _message: None, cancelled=None):
    """Analyze the full transcript in user-selected 3–15 minute windows."""
    if provider == "hooks":
        return None
    backend = {"ollama": _ollama, "gemini": _gemini, "huggingface": _huggingface,
               "custom": _openai_compatible}.get(provider)
    if backend is None:
        raise AIProviderError("Unknown highlight provider.")
    if provider == "gemini":
        config["_gemini_log"] = log
        config["_gemini_cancelled"] = cancelled
    config["_ai_log"] = log
    duration = max(0, float(duration))
    if not duration:
        return []
    picks = {}
    active_provider = provider
    active_backend = backend
    fell_back = False
    fallback_reason = ""
    try:
        window_minutes = int(config.get("ai_window_minutes", 5))
    except (TypeError, ValueError):
        window_minutes = 5
    window_size = max(180, min(900, window_minutes * 60))
    window_start = 0
    while window_start < duration:
        if cancelled and cancelled():
            raise AIAnalysisCancelled("AI highlight analysis stopped by user.")
        window_end = min(duration, window_start + window_size)
        local_words = [(max(0, float(s) - window_start), min(window_end - window_start, float(e) - window_start), text)
                       for s, e, text in words if window_start <= float(s) < window_end]
        if not local_words:
            window_start += window_size
            continue
        prompt = _prompt(local_words, window_end - window_start)
        config["_ai_window"] = (window_start, window_end)
        if active_provider == "fallback_exhausted":
            window_start += window_size
            continue
        try:
            raw = _call_backend(active_backend, prompt, config, cancelled)
            parsed_window = _parse_moments(raw, window_end - window_start)
        except AIProviderError as exc:
            if provider == "gemini" and active_provider == "gemini" and (exc.quota or exc.retryable):
                fallback_reason = "quota/rate limit" if exc.quota else "temporary model/API failures"
                log(f"Gemini rotations are exhausted ({fallback_reason}). Switching providers for this analysis; Gemini will be retried on the next video/task.")
                fallback_candidates = [("Ollama (local/free)", _ollama)]
                if str(config.get("huggingface_token", "")).strip():
                    fallback_candidates.append(("Hugging Face", _huggingface))
                if str(config.get("custom_api_base", "")).strip() and str(config.get("custom_api_model", "")).strip():
                    fallback_candidates.append(("custom OpenAI-compatible API", _openai_compatible))
                fallback_succeeded = False
                for fallback_name, fallback_fn in fallback_candidates:
                    try:
                        log(f"Trying fallback provider: {fallback_name}.")
                        raw = _call_backend(fallback_fn, prompt, config, cancelled)
                        parsed_window = _parse_moments(raw, window_end - window_start)
                        active_backend = fallback_fn
                        active_provider = fallback_name
                        log(f"Fallback provider {fallback_name} is working. It will handle the remaining windows in this analysis; Gemini remains selected for the next video/task.")
                        fallback_succeeded = True
                        fell_back = True
                        break
                    except AIAnalysisCancelled:
                        raise
                    except AIProviderError as fallback_error:
                        log(f"Fallback provider {fallback_name} failed: {fallback_error}")
                if not fallback_succeeded:
                    log("All configured fallback providers failed. Skipping remaining windows for this analysis; Gemini will be retried on the next video/task.")
                    active_provider = "fallback_exhausted"
                    window_start += window_size
                    continue
            else:
                log(f"{active_provider.title()} could not analyze transcript window {int(window_start)}–{int(window_end)}s: {exc}. Skipping this window; keeping earlier highlights.")
                window_start += window_size
                continue
        for second, score in parsed_window:
            absolute_second = int(window_start + second)
            calibrated_score = _calibrate_score(score, local_words, second)
            picks[absolute_second] = max(picks.get(absolute_second, 0.0), calibrated_score)
        window_start += window_size
    if fell_back:
        log(f"Remaining transcript windows were analyzed with Ollama after Gemini {fallback_reason}.")
    return sorted(picks.items())
