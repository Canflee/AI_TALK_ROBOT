import logging
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

logger = logging.getLogger(__name__)

RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, timeout: float, max_retries: int):
        if not api_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY")
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self.max_retries = max_retries

    def chat(self, messages: list[dict], model: str, temperature: float, max_tokens: int) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except RETRYABLE as exc:
                last_error = exc
                logger.warning("DeepSeek 请求失败(%s/%s): %s", attempt + 1, self.max_retries + 1, exc)
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                continue
            except APIStatusError as exc:
                raise DeepSeekError(f"DeepSeek 接口返回 {exc.status_code}") from exc
            except Exception as exc:
                raise DeepSeekError(f"调用 DeepSeek 失败: {exc}") from exc

            choice = response.choices[0]
            content = (choice.message.content or "").strip()
            if not content:
                raise DeepSeekError(
                    f"DeepSeek 返回了空内容（finish_reason={choice.finish_reason}，"
                    "可能是推理 token 用完了 max_tokens）"
                )
            return content

        raise DeepSeekError(f"DeepSeek 请求重试后仍失败: {last_error}")
