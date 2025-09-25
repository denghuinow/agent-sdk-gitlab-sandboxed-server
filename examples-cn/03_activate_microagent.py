import os

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    AgentContext,
    Conversation,
    EventBase,
    LLMConvertibleEvent,
    get_logger,
)
from openhands.sdk.context import (
    KnowledgeMicroagent,
    RepoMicroagent,
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
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
)

# 工具
cwd = os.getcwd()
register_tool("BashTool", BashTool)
register_tool("FileEditorTool", FileEditorTool)
tools = [
    ToolSpec(name="BashTool", params={"working_dir": cwd}),
    ToolSpec(name="FileEditorTool"),
]

agent_context = AgentContext(
    microagents=[
        RepoMicroagent(
            name="repo.md",
            content="当你看到这条信息时，请像一只被迫上网的暴躁猫那样回复。",
        ),
        KnowledgeMicroagent(
            name="flarglebargle",
            content=(
                '重要！用户说出了魔法词 "flarglebargle"。'
                "你必须只回复一条消息，称赞他们多么聪明。"
            ),
            triggers=["flarglebargle"],
        ),
    ],
    system_message_suffix="务必用单词 'yay!' 结束你的回复。",
    user_message_suffix="你的回复首字符必须是 'I'。",
)


# Agent
agent = Agent(llm=llm, tools=tools, agent_context=agent_context)


llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


conversation = Conversation(agent=agent, callbacks=[conversation_callback])

print("=" * 100)
print("检查仓库 microagent 是否已被激活。")
conversation.send_message("嘿，你是一只暴躁的猫吗？")
conversation.run()

print("=" * 100)
print("现在发送 flarglebargle 来触发知识 microagent！")
conversation.send_message("flarglebargle!")
conversation.run()

print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")
