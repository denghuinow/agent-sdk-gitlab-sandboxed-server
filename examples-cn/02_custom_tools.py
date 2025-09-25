"""高级示例：展示如何显式使用执行器并实现自定义 grep 工具。"""

import os
import shlex
from collections.abc import Sequence

from pydantic import Field, SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    EventBase,
    ImageContent,
    LLMConvertibleEvent,
    TextContent,
    Tool,
    get_logger,
)
from openhands.sdk.tool import (
    ActionBase,
    ObservationBase,
    ToolExecutor,
    ToolSpec,
    register_tool,
)
from openhands.tools.execute_bash import (
    BashExecutor,
    ExecuteBashAction,
    execute_bash_tool,
)
from openhands.tools.str_replace_editor import FileEditorTool


logger = get_logger(__name__)


# --- 行动 / 观测 ---


class GrepAction(ActionBase):
    pattern: str = Field(description="要搜索的正则表达式")
    path: str = Field(
        default=".",
        description="要搜索的目录（绝对路径或相对路径）",
    )
    include: str | None = Field(
        default=None, description="用于过滤文件的可选 glob（例如 '*.py')"
    )


class GrepObservation(ObservationBase):
    matches: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    count: int = 0

    @property
    def agent_observation(self) -> Sequence[TextContent | ImageContent]:
        if not self.count:
            return [TextContent(text="未找到任何匹配项。")]
        files_list = "\n".join(f"- {f}" for f in self.files[:20])
        sample = "\n".join(self.matches[:10])
        more = "\n..." if self.count > 10 else ""
        ret = (
            f"找到 {self.count} 行匹配结果。\n"
            f"文件列表：\n{files_list}\n"
            f"示例：\n{sample}{more}"
        )
        return [TextContent(text=ret)]


# --- 执行器 ---


class GrepExecutor(ToolExecutor[GrepAction, GrepObservation]):
    def __init__(self, bash: BashExecutor):
        self.bash = bash

    def __call__(self, action: GrepAction) -> GrepObservation:
        root = os.path.abspath(action.path)
        pat = shlex.quote(action.pattern)
        root_q = shlex.quote(root)

        # 使用 grep -r；当提供 include 时添加 --include
        if action.include:
            inc = shlex.quote(action.include)
            cmd = f"grep -rHnE --include {inc} {pat} {root_q} 2>/dev/null | head -100"
        else:
            cmd = f"grep -rHnE {pat} {root_q} 2>/dev/null | head -100"

        result = self.bash(ExecuteBashAction(command=cmd))

        matches: list[str] = []
        files: set[str] = set()

        # 当没有匹配项时，grep 会返回退出码 1；将其视作无数据
        if result.output.strip():
            for line in result.output.strip().splitlines():
                matches.append(line)
                # 预期格式为 "path:line:content" —— 取第一个冒号之前的文件部分
                file_path = line.split(":", 1)[0]
                if file_path:
                    files.add(os.path.abspath(file_path))

        return GrepObservation(matches=matches, files=sorted(files), count=len(matches))


# 工具描述
_GREP_DESCRIPTION = """高速内容检索工具。
* 通过正则表达式搜索文件内容
* 支持完整的正则语法（例如 "log.*Error"、"function\\s+\\w+" 等）
* 通过 include 参数过滤文件（例如 "*.js"、"*.{ts,tsx}"）
* 返回匹配文件路径，并按修改时间排序。
* 仅返回前 100 条结果。如需更多结果，请使用更严格的正则或提供 path 参数缩小范围。
* 当你需要查找包含特定模式的文件时，请使用该工具。
* 如果你在进行开放式搜索，可能需要多轮 glob 与 grep，请改用 Agent 工具。
"""

# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"
llm = LLM(
    service_id="main-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://oneapi.wchat.cc/v1",
    api_key=SecretStr(api_key),
)

# 工具 —— 同时展示简化用法与高级用法
cwd = os.getcwd()


def _make_bash_and_grep_tools(working_dir: str) -> list[Tool]:
    """创建共享同一个执行器的 execute_bash 与自定义 grep 工具。"""

    bash_executor = BashExecutor(working_dir=working_dir)
    bash_tool = execute_bash_tool.set_executor(executor=bash_executor)

    grep_executor = GrepExecutor(bash_executor)
    grep_tool = Tool(
        name="grep",
        description=_GREP_DESCRIPTION,
        action_type=GrepAction,
        observation_type=GrepObservation,
        executor=grep_executor,
    )

    return [bash_tool, grep_tool]


register_tool("FileEditorTool", FileEditorTool)
register_tool("BashAndGrepToolSet", _make_bash_and_grep_tools)

tools = [
    ToolSpec(name="FileEditorTool"),
    ToolSpec(name="BashAndGrepToolSet", params={"working_dir": cwd}),
]

# Agent
agent = Agent(llm=llm, tools=tools)

llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


conversation = Conversation(agent=agent, callbacks=[conversation_callback])

conversation.send_message(
    "你好！请使用 grep 工具查找项目中包含单词 'class' 的所有文件，"
    "然后创建一个摘要文件列出它们。"
    "使用模式 'class' 进行搜索，并仅包含 '*.py' 的 Python 文件。"
)
conversation.run()

conversation.send_message("干得好！现在删除那个文件。")
conversation.run()

print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")
