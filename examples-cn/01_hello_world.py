import os

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Conversation,
    EventBase,
    LLMConvertibleEvent,
    get_logger,
)
from openhands.sdk.preset.default import get_default_agent


logger = get_logger(__name__)

# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"
llm = LLM(
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
    service_id="hello-world-llm",
)

cwd = os.getcwd()
agent = get_default_agent(
    llm=llm,
    working_dir=cwd,
    # CLI 模式会禁用任何浏览器工具
    # 这些工具依赖例如 playwright 之类的依赖，可能并非所有环境都具备。
    cli_mode=True,
)
# # 另外，你也可以手动注册工具并为 Agent 提供 ToolSpec。
# from openhands.sdk import Agent
# from openhands.sdk.tool.registry import register_tool
# from openhands.sdk.tool.spec import ToolSpec
# from openhands.tools.execute_bash import BashTool
# from openhands.tools.str_replace_editor import FileEditorTool
# from openhands.tools.task_tracker import TaskTrackerTool
# register_tool("BashTool", BashTool)
# register_tool("FileEditorTool", FileEditorTool)
# register_tool("TaskTrackerTool", TaskTrackerTool)

# # 提供 ToolSpec 让 Agent 可以在运行时按需实例化工具。
# agent = Agent(
#     llm=llm,
#     tools=[
#         ToolSpec(name="BashTool", params={"working_dir": cwd}),
#         ToolSpec(name="FileEditorTool"),
#         ToolSpec(name="TaskTrackerTool", params={"save_dir": cwd}),
#     ],
# )

llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


conversation = Conversation(agent=agent, callbacks=[conversation_callback])

conversation.send_message(
    "阅读当前仓库并将关于该项目的 3 个事实写入 FACTS.txt。"
)
conversation.run()

conversation.send_message("太好了！现在删除那个文件。")
conversation.run()


print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")
