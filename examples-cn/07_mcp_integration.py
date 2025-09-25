import os

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    EventBase,
    LLMConvertibleEvent,
    get_logger,
)
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.tools.execute_bash import BashTool
from openhands.tools.str_replace_editor import FileEditorTool


logger = get_logger(__name__)

# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"
llm = LLM(
    service_id="main-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://oneapi.wchat.cc/v1",
    api_key=SecretStr(api_key),
)

cwd = os.getcwd()
register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
tool_specs = [
    ToolSpec(name="BashTool", params={"working_dir": cwd}),
    ToolSpec(name="FileEditorTool"),
]

# 添加 MCP 工具
mcp_config = {
    "mcpServers": {
        "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
        "repomix": {"command": "npx", "args": ["-y", "repomix@1.4.2", "--mcp"]},
    }
}
# Agent
agent = Agent(
    llm=llm,
    tools=tool_specs,
    mcp_config=mcp_config,
    # 该正则会过滤掉除 pack_codebase 外的所有 repomix 工具
    filter_tools_regex="^(?!repomix)(.*)|^repomix.*pack_codebase.*$",
)

llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


# 对话
conversation = Conversation(
    agent=agent,
    callbacks=[conversation_callback],
)

logger.info("开始带有 MCP 集成的对话…")
conversation.send_message(
    "阅读 https://github.com/All-Hands-AI/OpenHands 并将关于该项目的 3 个事实"
    "写入 FACTS.txt。"
)
conversation.run()

conversation.send_message("太棒了！现在删除那个文件。")
conversation.run()

print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")
