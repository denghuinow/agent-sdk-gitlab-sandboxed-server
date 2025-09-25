import os

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    EventBase,
    ImageContent,
    LLMConvertibleEvent,
    Message,
    TextContent,
    get_logger,
)
from openhands.sdk.llm.router import MultimodalRouter
from openhands.sdk.preset.default import get_default_tools


logger = get_logger(__name__)

# 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

primary_llm = LLM(
    service_id="primary-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
)
secondary_llm = LLM(
    service_id="secondary-llm",
    model="litellm_proxy/mistral/devstral-small-2507",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
)
multimodal_router = MultimodalRouter(
    service_id="multimodal-router",
    llms_for_routing={"primary": primary_llm, "secondary": secondary_llm},
)

# 工具
cwd = os.getcwd()
tools = get_default_tools(working_dir=cwd)  # 使用默认的 OpenHands 体验

# Agent
agent = Agent(llm=multimodal_router, tools=tools)

llm_messages = []  # 收集原始 LLM 消息


def conversation_callback(event: EventBase):
    if isinstance(event, LLMConvertibleEvent):
        llm_messages.append(event.to_llm_message())


conversation = Conversation(agent=agent, callbacks=[conversation_callback])

conversation.send_message(
    message=Message(
        role="user",
        content=[TextContent(text="你好，谁训练了你？")],
    )
)
conversation.run()

conversation.send_message(
    message=Message(
        role="user",
        content=[
            ImageContent(
                image_urls=["http://images.cocodataset.org/val2017/000000039769.jpg"]
            ),
            TextContent(text="你在上面的图片中看到了什么？"),
        ],
    )
)
conversation.run()

conversation.send_message(
    message=Message(
        role="user",
        content=[TextContent(text="谁训练了你这个 LLM？")],
    )
)
conversation.run()


print("=" * 100)
print("对话结束。以下是获取的 LLM 消息：")
for i, message in enumerate(llm_messages):
    print(f"消息 {i}: {str(message)[:200]}")
