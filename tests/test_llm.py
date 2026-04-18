from unittest.mock import MagicMock, patch

import pytest

from miniflux_summarizer.llm import generate_summary


@patch("miniflux_summarizer.llm.OpenAI")
def test_generate_summary(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Summary result"))]
    mock_client.chat.completions.create.return_value = mock_response

    result = generate_summary(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
        system_prompt="You are a summarizer.",
        entries_text="Article 1 content\nArticle 2 content",
    )

    assert result == "Summary result"
    mock_client.chat.completions.create.assert_called_once_with(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a summarizer."},
            {"role": "user", "content": "Article 1 content\nArticle 2 content"},
        ],
    )


@patch("miniflux_summarizer.llm.OpenAI")
def test_generate_summary_passes_model_and_url(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_client.chat.completions.create.return_value = mock_response

    generate_summary(
        base_url="https://llm.custom.com/v1",
        api_key="key",
        model="llama3",
        system_prompt="prompt",
        entries_text="text",
    )

    MockOpenAI.assert_called_once_with(
        base_url="https://llm.custom.com/v1",
        api_key="key",
        timeout=60.0,
    )
