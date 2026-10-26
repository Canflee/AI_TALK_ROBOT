import logging

from ..llm.aimodel import AIModelClient, AIModelError

logger = logging.getLogger(__name__)

DOC_MAX_INPUT_CHARS = 50000
DOC_OUTPUT_TOKEN_FALLBACK = (8000, 16000)

SYSTEM_PROMPT = """你是一个文档处理助手。根据用户的要求处理给出的文档内容。
只输出处理后的最终正文，不要解释你的思路，不要写“以下是”之类的开场白。
用纯文本输出：标题可以单独一行，列表用“- ”开头；不要使用 Markdown 代码块或表格。
保留原文的事实、数字和专有名词；原文没有的信息不要编造。
如果原文内容不完整，按现有内容处理，不要猜测缺失部分。"""


def process_document(
    llm: AIModelClient,
    source_name: str,
    text: str,
    instruction: str,
    model: str,
    max_tokens: int = DOC_OUTPUT_TOKEN_FALLBACK[0],
    retry_max_tokens: int = DOC_OUTPUT_TOKEN_FALLBACK[1],
) -> str:
    note = ""
    if len(text) > DOC_MAX_INPUT_CHARS:
        text = text[:DOC_MAX_INPUT_CHARS]
        note = f"\n\n[注意：文档过长，下面只提供前 {DOC_MAX_INPUT_CHARS} 字]"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"文档名：{source_name}\n"
                f"处理要求：{instruction}\n\n"
                f"文档内容：\n{text}{note}"
            ),
        },
    ]
    last_error: Exception | None = None
    steps = tuple(dict.fromkeys((max_tokens, retry_max_tokens)))
    for token_budget in steps:
        try:
            return llm.chat(
                messages,
                model=model,
                temperature=0.3,
                max_tokens=token_budget,
            )
        except AIModelError as exc:
            last_error = exc
            if "空内容" not in str(exc):
                raise
            logger.warning("文档处理返回空内容，提高 token 后重试：max_tokens=%s", token_budget)
    raise last_error or AIModelError("文档处理失败")
