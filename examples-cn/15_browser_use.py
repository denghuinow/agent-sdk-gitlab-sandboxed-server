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
from openhands.tools.browser_use import BrowserToolSet
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

# 工具
cwd = os.getcwd()
register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
register_tool("BrowserToolSet", BrowserToolSet)
tools = [
    ToolSpec(name="BashTool", params={"working_dir": cwd}),
    ToolSpec(name="FileEditorTool"),
    ToolSpec(name="BrowserToolSet"),
]

# 如果需要更细粒度的浏览器控制，可以创建 BrowserToolExecutor，
# 并提供返回定制 Tool 实例的工厂函数，在构建 Agent 前手动注册每个浏览器工具。

# Agent
agent = Agent(llm=llm, tools=tools)

llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


conversation = Conversation(agent=agent, callbacks=[conversation_callback])

conversation.send_message(
    "请访问 https://all-hands.dev/ 的博客页面，"
    "并总结最新一篇博客的要点。"
)
conversation.run()


print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")
