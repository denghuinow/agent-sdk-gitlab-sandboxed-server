"""Tests for the Tool class in openhands.sdk.runtime.tool."""

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import Field, ValidationError

from openhands.sdk.llm.message import ImageContent, TextContent
from openhands.sdk.tool import (
    ActionBase,
    ObservationBase,
    Tool,
    ToolAnnotations,
    ToolExecutor,
)


class TestToolImmutabilityMockAction(ActionBase):
    """Mock action class for testing."""

    command: str = Field(description="Command to execute")
    optional_field: str | None = Field(default=None, description="Optional field")
    nested: dict[str, Any] = Field(default_factory=dict, description="Nested object")
    array_field: list[int] = Field(default_factory=list, description="Array field")


class TestToolImmutabilityMockObservation(ObservationBase):
    """Mock observation class for testing."""

    result: str = Field(description="Result of the action")
    extra_field: str | None = Field(default=None, description="Extra field")

    @property
    def agent_observation(self) -> Sequence[TextContent | ImageContent]:
        return [TextContent(text=self.result)]


class TestToolImmutability:
    """Test suite for Tool immutability features."""

    def test_tool_is_frozen(self):
        """Test that Tool instances are frozen and cannot be modified."""
        tool = Tool(
            name="test_tool",
            description="Test tool",
            action_type=TestToolImmutabilityMockAction,
            observation_type=TestToolImmutabilityMockObservation,
        )

        # Test that we cannot modify any field
        with pytest.raises(
            Exception
        ):  # Pydantic raises ValidationError for frozen models
            tool.name = "modified_name"

        with pytest.raises(Exception):
            tool.description = "modified_description"

        with pytest.raises(Exception):
            tool.executor = None

    def test_tool_set_executor_returns_new_instance(self):
        """Test that set_executor returns a new Tool instance."""
        tool = Tool(
            name="test_tool",
            description="Test tool",
            action_type=TestToolImmutabilityMockAction,
            observation_type=TestToolImmutabilityMockObservation,
        )

        class NewExecutor(
            ToolExecutor[
                TestToolImmutabilityMockAction, TestToolImmutabilityMockObservation
            ]
        ):
            def __call__(
                self, action: TestToolImmutabilityMockAction
            ) -> TestToolImmutabilityMockObservation:
                return TestToolImmutabilityMockObservation(result="new_result")

        new_executor = NewExecutor()
        new_tool = tool.set_executor(new_executor)

        # Verify that a new instance was created
        assert new_tool is not tool
        assert tool.executor is None
        assert new_tool.executor is new_executor
        assert new_tool.name == tool.name
        assert new_tool.description == tool.description

    def test_tool_model_copy_creates_modified_instance(self):
        """Test that model_copy can create modified versions of Tool instances."""
        tool = Tool(
            name="test_tool",
            description="Test tool",
            action_type=TestToolImmutabilityMockAction,
            observation_type=TestToolImmutabilityMockObservation,
        )

        # Create a copy with modified fields
        modified_tool = tool.model_copy(
            update={"name": "modified_tool", "description": "Modified description"}
        )

        # Verify that a new instance was created with modifications
        assert modified_tool is not tool
        assert tool.name == "test_tool"
        assert tool.description == "Test tool"
        assert modified_tool.name == "modified_tool"
        assert modified_tool.description == "Modified description"

    def test_tool_meta_field_immutability(self):
        """Test that the meta field works correctly and is immutable."""
        meta_data = {"version": "1.0", "author": "test"}
        tool = Tool(
            name="test_tool",
            description="Test tool",
            action_type=TestToolImmutabilityMockAction,
            observation_type=TestToolImmutabilityMockObservation,
            meta=meta_data,
        )

        # Verify meta field is accessible
        assert tool.meta == meta_data

        # Test that meta field cannot be directly modified
        with pytest.raises(Exception):
            tool.meta = {"version": "2.0"}

        # Test that meta field can be modified via model_copy
        new_meta = {"version": "2.0", "author": "new_author"}
        modified_tool = tool.model_copy(update={"meta": new_meta})
        assert modified_tool.meta == new_meta
        assert tool.meta == meta_data  # Original unchanged

    def test_tool_constructor_parameter_validation(self):
        """Test that Tool constructor validates parameters correctly."""
        # Test that new parameter names work
        tool = Tool(
            name="test_tool",
            description="Test tool",
            action_type=TestToolImmutabilityMockAction,
            observation_type=TestToolImmutabilityMockObservation,
        )
        assert tool.action_type == TestToolImmutabilityMockAction
        assert tool.observation_type == TestToolImmutabilityMockObservation

        # Test that invalid field types are rejected
        with pytest.raises(ValidationError):
            Tool(
                name="test_tool",
                description="Test tool",
                action_type="invalid_type",  # type: ignore[arg-type] # Should be a class, not string
                observation_type=TestToolImmutabilityMockObservation,
            )

    def test_tool_annotations_immutability(self):
        """Test that ToolAnnotations are also immutable when part of Tool."""
        annotations = ToolAnnotations(
            title="Test Tool",
            readOnlyHint=True,
            destructiveHint=False,
        )

        tool = Tool(
            name="test_tool",
            description="Test tool",
            action_type=TestToolImmutabilityMockAction,
            observation_type=TestToolImmutabilityMockObservation,
            annotations=annotations,
        )

        # Test that annotations field cannot be reassigned (frozen behavior)
        with pytest.raises(Exception):
            tool.annotations = ToolAnnotations(title="New Annotations")

        # Test that annotations can be modified via model_copy
        new_annotations = ToolAnnotations(
            title="Modified Tool",
            readOnlyHint=False,
            destructiveHint=True,
        )
        modified_tool = tool.model_copy(update={"annotations": new_annotations})
        assert (
            modified_tool.annotations
            and modified_tool.annotations.title == "Modified Tool"
        )
        assert (
            tool.annotations and tool.annotations.title == "Test Tool"
        )  # Original unchanged
