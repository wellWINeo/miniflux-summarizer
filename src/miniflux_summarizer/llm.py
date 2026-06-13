from openai import APIError, OpenAI

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion

def generate_summary(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    entries_text: str,
) -> str:
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0)

    try:
        response: ChatCompletion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": entries_text},
            ],
        )
    except APIError as exc:
        raise RuntimeError(f"LLM API call failed: {exc}") from exc

    if not response.choices:
        raise RuntimeError("LLM returned no choices")

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("LLM returned no content")
    return content
