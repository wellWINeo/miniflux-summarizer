from openai import APIError, OpenAI


def generate_summary(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    entries_text: str,
) -> str:
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0)

    try:
        response = client.chat.completions.create(
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

    return response.choices[0].message.content
