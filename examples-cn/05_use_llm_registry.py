import os

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    EventBase,
    LLMConvertibleEvent,
    LLMRegistry,
    Message,
    TextContent,
    get_logger,
)
from openhands.sdk.tool import ToolSpec, register_tool
from openhands.tools.execute_bash import BashTool


logger = get_logger(__name__)

# 使用 LLMRegistry 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

# 创建 LLM 实例
main_llm = LLM(
    service_id="primary-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
)

# 创建 LLM 注册表并加入该 LLM
llm_registry = LLMRegistry()
llm_registry.add(main_llm)

# 从注册表中获取 LLM
llm = llm_registry.get("main_agent")

# 工具
cwd = os.getcwd()
register_tool("BashTool", BashTool)
tools = [ToolSpec(name="BashTool", params={"working_dir": cwd})]

# Agent
agent = Agent(llm=llm, tools=tools)

llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


conversation = Conversation(agent=agent, callbacks=[conversation_callback])

conversation.send_message("请执行 echo 'Hello!'")
conversation.run()

print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")

print("=" * 100)
print(f"LLM 注册表中的服务：{llm_registry.list_services()}")

# 演示从注册表中获取同一个 LLM 实例
same_llm = llm_registry.get("main_agent")
print(f"是否同一个 LLM 实例：{llm is same_llm}")

# 演示直接向 LLM 请求补全
completion_response = llm.completion(
    messages=[
        Message(role="user", content=[TextContent(text="用一个词向我问好。")])
    ]
)
# 访问响应内容
if completion_response.choices and completion_response.choices[0].message:  # type: ignore
    content = completion_response.choices[0].message.content  # type: ignore
    print(f"直接补全结果：{content}")
else:
    print("没有可用的响应内容")
