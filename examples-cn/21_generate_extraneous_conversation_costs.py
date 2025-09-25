import os

from pydantic import SecretStr
from tabulate import tabulate

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    LLMSummarizingCondenser,
    Message,
    TextContent,
    get_logger,
)
from openhands.sdk.tool.registry import register_tool
from openhands.sdk.tool.spec import ToolSpec
from openhands.tools.execute_bash import (
    BashTool,
)


logger = get_logger(__name__)

# 使用 LLMRegistry 配置 LLM
api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

# 创建 LLM 实例
llm = LLM(
    service_id="main-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
)

llm_condenser = LLM(
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
    service_id="condenser",
)

# 工具
register_tool("BashTool", BashTool)

condenser = LLMSummarizingCondenser(llm=llm_condenser, max_size=10, keep_first=2)

cwd = os.getcwd()
agent = Agent(
    llm=llm,
    tools=[
        ToolSpec(name="BashTool", params={"working_dir": cwd}),
    ],
    condenser=condenser,
)

conversation = Conversation(agent=agent)
conversation.send_message(
    message=Message(
        role="user",
        content=[TextContent(text="请执行 echo 'Hello!'")],
    )
)
conversation.run()


# 展示对话中额外产生费用的部分
second_llm = LLM(
    service_id="secondary-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
)
conversation.llm_registry.add(second_llm)
completion_response = second_llm.completion(
    messages=[Message(role="user", content=[TextContent(text="echo 'More spend!'")])]
)


# 获取总消耗
spend = conversation.conversation_stats.get_combined_metrics()
print("\n=== 对话总花费 ===\n")
print(f"累计费用：${spend.accumulated_cost:.6f}")
if spend.accumulated_token_usage:
    print(f"提示词 Token：{spend.accumulated_token_usage.prompt_tokens}")
    print(f"补全 Token：{spend.accumulated_token_usage.completion_tokens}")
    print(f"缓存读取 Token：{spend.accumulated_token_usage.cache_read_tokens}")
    print(f"缓存写入 Token：{spend.accumulated_token_usage.cache_write_tokens}")


spend_per_service = conversation.conversation_stats.service_to_metrics
print("\n=== 各服务花费明细 ===\n")
rows = []
for service, metrics in spend_per_service.items():
    rows.append(
        [
            service,
            f"${metrics.accumulated_cost:.6f}",
            metrics.accumulated_token_usage.prompt_tokens
            if metrics.accumulated_token_usage
            else 0,
            metrics.accumulated_token_usage.completion_tokens
            if metrics.accumulated_token_usage
            else 0,
        ]
    )

print(
    tabulate(
        rows,
        headers=["服务", "费用", "提示词 Token", "补全 Token"],
        tablefmt="github",
    )
)
