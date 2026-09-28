import os
import time
from dataclasses import dataclass

import httpx
from .config import integer


class LLMError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class Provider:
    name: str

    def generate_answer(self, system_prompt: str, user_prompt: str) -> str:
        settings = {
            "gemini": ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini-3.6-flash"),
            "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4.1-mini"),
            "groq": ("GROQ_API_KEY", "GROQ_MODEL", "llama-3.3-70b-versatile"),
        }
        if self.name not in settings:
            raise LLMError("unsupported_provider")
        key_var, model_var, default_model = settings[self.name]
        key = os.getenv(key_var, "").strip()
        if not key:
            raise LLMError("missing_api_key")
        model = os.getenv(model_var, default_model)
        if self.name == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            headers = {"x-goog-api-key": key}
            payload = {"system_instruction": {"parts": [{"text": system_prompt}]},
                       "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                       "generationConfig": {"temperature": 0.1, "maxOutputTokens": integer("GEMINI_MAX_OUTPUT_TOKENS", 8192, maximum=32768)}}
        else:
            url = "https://api.openai.com/v1/chat/completions" if self.name == "openai" else "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}"}
            payload = {"model": model, "temperature": 0.1, "max_tokens": 1200,
                       "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]}
        try:
            timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "35"))
            deadline = time.monotonic() + timeout
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                # A transient overload is not a bad key. Retry once within the
                # original request budget, without retrying auth or quota errors.
                if response.status_code in {502, 503, 504}:
                    remaining = deadline - time.monotonic()
                    if remaining > 1:
                        response = client.post(url, headers=headers, json=payload, timeout=remaining)
            if response.status_code in {502, 503, 504}:
                raise LLMError("provider_unavailable")
            if response.status_code == 429:
                raise LLMError("quota_exceeded")
            if response.status_code in {401, 403}:
                raise LLMError("authentication_failed")
            response.raise_for_status()
            data = response.json()
            if self.name == "gemini":
                candidate = data["candidates"][0]
                if candidate.get("finishReason") not in {None, "STOP"}:
                    raise LLMError("incomplete_response")
                answer = "\n".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
            else:
                choice = data["choices"][0]
                if choice.get("finish_reason") not in {None, "stop"}:
                    raise LLMError("incomplete_response")
                answer = choice["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise LLMError("empty_response")
            return answer.strip()
        except LLMError:
            raise
        except httpx.TimeoutException:
            raise LLMError("timeout") from None
        except Exception:
            # Never expose upstream bodies/URLs/credentials in API responses or logs.
            raise LLMError("provider_error") from None


def generate_answer(system_prompt: str, user_prompt: str) -> str:
    return Provider(os.getenv("LLM_PROVIDER", "gemini").strip().lower()).generate_answer(system_prompt, user_prompt)
