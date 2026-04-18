from openai import OpenAI


def generate_summary(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    entries_text: str,
) -> str:
    client = OpenAI(base_url=base_url, api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": entries_text},
        ],
    )

    return response.choices[0].message.content
