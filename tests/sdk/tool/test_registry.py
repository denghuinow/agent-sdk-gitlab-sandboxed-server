from collections.abc import Sequence

import pytest

from openhands.sdk import register_tool
from openhands.sdk.llm.message import ImageContent, TextContent
from openhands.sdk.tool import Tool
from openhands.sdk.tool.registry import resolve_tool
from openhands.sdk.tool.schema import ActionBase, ObservationBase
from openhands.sdk.tool.spec import ToolSpec
from openhands.sdk.tool.tool import ToolExecutor


class _HelloAction(ActionBase):
    name: str


class _HelloObservation(ObservationBase):
    message: str

    @property
    def agent_observation(self) -> Sequence[TextContent | ImageContent]:
        return [TextContent(text=self.message)]


class _HelloExec(ToolExecutor[_HelloAction, _HelloObservation]):
    def __call__(self, action: _HelloAction) -> _HelloObservation:
        return _HelloObservation(message=f"Hello, {action.name}!")


class _ConfigurableHelloTool(Tool):
    @classmethod
    def create(cls, greeting: str = "Hello", punctuation: str = "!"):
        class _ConfigurableExec(ToolExecutor[_HelloAction, _HelloObservation]):
            def __init__(self, greeting: str, punctuation: str) -> None:
                self._greeting = greeting
                self._punctuation = punctuation

            def __call__(self, action: _HelloAction) -> _HelloObservation:
                return _HelloObservation(
                    message=f"{self._greeting}, {action.name}{self._punctuation}"
                )

        return [
            cls(
                name="say_configurable_hello",
                description=f"{greeting}{punctuation}",
                action_type=_HelloAction,
                observation_type=_HelloObservation,
                executor=_ConfigurableExec(greeting, punctuation),
            )
        ]


def _hello_tool_factory() -> list[Tool]:
    return [
        Tool(
            name="say_hello",
            description="Says hello",
            action_type=_HelloAction,
            observation_type=_HelloObservation,
            executor=_HelloExec(),
        )
    ]


def test_register_and_resolve_callable_factory():
    register_tool("say_hello", _hello_tool_factory)
    tools = resolve_tool(ToolSpec(name="say_hello"))
    assert len(tools) == 1
    assert isinstance(tools[0], Tool)
    assert tools[0].name == "say_hello"


def test_register_tool_instance_rejects_params():
    t = _hello_tool_factory()[0]  # Get the single tool from the list
    register_tool("say_hello_instance", t)
    with pytest.raises(ValueError):
        resolve_tool(ToolSpec(name="say_hello_instance", params={"x": 1}))


def test_register_tool_instance_returns_same_object():
    tool = _hello_tool_factory()[0]  # Get the single tool from the list
    register_tool("say_hello_instance_same", tool)

    resolved_first = resolve_tool(ToolSpec(name="say_hello_instance_same"))
    resolved_second = resolve_tool(ToolSpec(name="say_hello_instance_same"))

    assert resolved_first == [tool]
    assert resolved_first[0] is tool
    assert resolved_second[0] is tool


def test_register_tool_type_uses_create_params():
    register_tool("say_configurable_hello_type", _ConfigurableHelloTool)

    tools = resolve_tool(
        ToolSpec(
            name="say_configurable_hello_type",
            params={"greeting": "Howdy", "punctuation": "?"},
        )
    )

    assert len(tools) == 1
    tool = tools[0]
    assert isinstance(tool, _ConfigurableHelloTool)
    assert tool.description == "Howdy?"

    observation = tool(_HelloAction(name="Alice"))
    assert isinstance(observation, _HelloObservation)
    assert observation.message == "Howdy, Alice?"
