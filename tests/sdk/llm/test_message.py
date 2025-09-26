from unittest.mock import patch

import pytest


def test_content_base_class_not_implemented():
    """Test that Content base class cannot be instantiated due to abstract method."""
    from openhands.sdk.llm.message import BaseContent

    with pytest.raises(TypeError, match="Can't instantiate abstract class BaseContent"):
        BaseContent()  # type: ignore[abstract]


def test_text_content_with_cache_prompt():
    """Test TextContent with cache_prompt enabled."""
    from openhands.sdk.llm.message import TextContent

    content = TextContent(text="Hello world", cache_prompt=True)
    result = content.to_llm_dict()

    assert len(result) == 1
    assert result[0]["type"] == "text"
    assert result[0]["text"] == "Hello world"
    assert result[0]["cache_control"] == {"type": "ephemeral"}


def test_image_content_with_cache_prompt():
    """Test ImageContent with cache_prompt enabled."""
    from openhands.sdk.llm.message import ImageContent

    content = ImageContent(
        image_urls=["data:image/png;base64,abc123", "data:image/jpeg;base64,def456"],
        cache_prompt=True,
    )
    result = content.to_llm_dict()

    assert len(result) == 2
    assert result[0]["type"] == "image_url"
    assert result[0]["image_url"]["url"] == "data:image/png;base64,abc123"  # type: ignore
    assert result[1]["type"] == "image_url"
    assert result[1]["image_url"]["url"] == "data:image/jpeg;base64,def456"  # type: ignore
    # Only the last image should have cache_control
    assert "cache_control" not in result[0]
    assert result[1]["cache_control"] == {"type": "ephemeral"}


def test_message_contains_image_property():
    """Test Message.contains_image property."""
    from openhands.sdk.llm.message import ImageContent, Message, TextContent

    # Message with only text content
    text_message = Message(role="user", content=[TextContent(text="Hello")])
    assert not text_message.contains_image

    # Message with image content
    image_message = Message(
        role="user",
        content=[
            TextContent(text="Look at this:"),
            ImageContent(
                image_urls=["data:image/png;base64,abc123"],
            ),
        ],
    )
    assert image_message.contains_image


def test_message_tool_role_with_cache_prompt():
    """Test Message with tool role and cache_prompt."""
    from openhands.sdk.llm.message import Message, TextContent

    message = Message(
        role="tool",
        content=[TextContent(text="Tool response", cache_prompt=True)],
        tool_call_id="call_123",
        name="test_tool",
        cache_enabled=True,
    )

    result = message.to_llm_dict()
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_123"
    assert result["cache_control"] == {"type": "ephemeral"}
    # The content should not have cache_control since it's moved to message level
    assert "cache_control" not in result["content"][0]


def test_message_tool_role_with_image_cache_prompt():
    """Test Message with tool role and ImageContent with cache_prompt."""
    from openhands.sdk.llm.message import ImageContent, Message

    message = Message(
        role="tool",
        content=[
            ImageContent(
                image_urls=["data:image/png;base64,abc123"],
                cache_prompt=True,
            )
        ],
        tool_call_id="call_123",
        name="test_tool",
        vision_enabled=True,
        cache_enabled=True,
    )

    result = message.to_llm_dict()
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_123"
    assert result["cache_control"] == {"type": "ephemeral"}
    # The image content should not have cache_control since it's moved to message level
    assert "cache_control" not in result["content"][0]


def test_message_with_tool_calls():
    """Test Message with tool_calls."""
    from litellm.types.utils import ChatCompletionMessageToolCall, Function

    from openhands.sdk.llm.message import Message, TextContent

    tool_call = ChatCompletionMessageToolCall(
        id="call_123",
        type="function",
        function=Function(name="test_function", arguments='{"arg": "value"}'),
    )

    message = Message(
        role="assistant",
        content=[TextContent(text="I'll call a function")],
        tool_calls=[tool_call],
    )

    result = message.to_llm_dict()
    assert result["role"] == "assistant"
    assert "tool_calls" in result
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["id"] == "call_123"
    assert result["tool_calls"][0]["type"] == "function"
    assert result["tool_calls"][0]["function"]["name"] == "test_function"
    assert result["tool_calls"][0]["function"]["arguments"] == '{"arg": "value"}'


def test_message_from_litellm_message_function_role_error():
    """Test Message.from_litellm_message with function role raises error."""
    from litellm.types.utils import Message as LiteLLMMessage

    from openhands.sdk.llm.message import Message

    litellm_message = LiteLLMMessage(role="function", content="Function response")  # type: ignore

    with pytest.raises(AssertionError, match="Function role is not supported"):
        Message.from_litellm_message(litellm_message)


def test_message_from_litellm_message_with_non_string_content():
    """Test Message.from_litellm_message with non-string content."""
    from litellm.types.utils import Message as LiteLLMMessage

    from openhands.sdk.llm.message import Message

    # Create a message with non-string content (None or list)
    litellm_message = LiteLLMMessage(role="assistant", content=None)

    result = Message.from_litellm_message(litellm_message)
    assert result.role == "assistant"
    assert result.content == []  # Empty list for non-string content


def test_text_content_truncation_under_limit():
    """Test TextContent doesn't truncate when under limit."""
    from openhands.sdk.llm.message import TextContent

    content = TextContent(text="Short text")
    result = content.to_llm_dict()

    assert len(result) == 1
    assert result[0]["text"] == "Short text"


def test_text_content_truncation_over_limit():
    """Test TextContent truncates when over limit."""
    from openhands.sdk.llm.message import TextContent
    from openhands.sdk.utils import DEFAULT_TEXT_CONTENT_LIMIT

    # Create text that exceeds the limit
    long_text = "A" * (DEFAULT_TEXT_CONTENT_LIMIT + 1000)

    with patch("openhands.sdk.llm.message.logger") as mock_logger:
        content = TextContent(text=long_text)
        result = content.to_llm_dict()

        # Check that warning was logged
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "exceeds limit" in warning_call
        assert str(DEFAULT_TEXT_CONTENT_LIMIT + 1000) in warning_call
        assert str(DEFAULT_TEXT_CONTENT_LIMIT) in warning_call

        # Check that text was truncated
        assert len(result) == 1
        text_result = result[0]["text"]
        assert isinstance(text_result, str)
        assert len(text_result) < len(long_text)
        assert len(text_result) == DEFAULT_TEXT_CONTENT_LIMIT
        # With head-and-tail truncation, should start and end with original content
        assert text_result.startswith("A")  # Should start with original content
        assert text_result.endswith("A")  # Should end with original content
        assert "<response clipped>" in text_result  # Should contain truncation notice


def test_text_content_truncation_exact_limit():
    """Test TextContent doesn't truncate when exactly at limit."""
    from openhands.sdk.llm.message import TextContent
    from openhands.sdk.utils import DEFAULT_TEXT_CONTENT_LIMIT

    # Create text that is exactly at the limit
    exact_text = "A" * DEFAULT_TEXT_CONTENT_LIMIT

    with patch("openhands.sdk.llm.message.logger") as mock_logger:
        content = TextContent(text=exact_text)
        result = content.to_llm_dict()

        # Check that no warning was logged
        mock_logger.warning.assert_not_called()

        # Check that text was not truncated
        assert len(result) == 1
        assert result[0]["text"] == exact_text
