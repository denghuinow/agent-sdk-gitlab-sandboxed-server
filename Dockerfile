# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 系统依赖：Git 用于仓库克隆；docker.io 提供 docker CLI；构建工具支持部分 Python 依赖编译。
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        docker-cli \
        git \
        openssh-client && \
    rm -rf /var/lib/apt/lists/*

# 复制并安装项目依赖（先装 SDK，再装 tools，最后装 agent_server，避免从 PyPI 拉取本地包依赖）。
COPY openhands ./openhands
RUN pip install --upgrade pip setuptools wheel && \
    pip install ./openhands/sdk && \
    pip install ./openhands/tools && \
    pip install ./openhands/agent_server

# 复制服务代码与相关资源。
COPY git_workspace_agent ./git_workspace_agent
COPY README.md README-CN.md AGENTS.md DEBUGGING.md LICENSE pyproject.toml uv.lock ./

# 默认工作区配置，实际运行时可通过环境变量覆盖。
ENV HOST_WORKSPACE_DIR=/tmp/git-workspace-agent \
    OH_WORKSPACE_PATH=/workspace \
    OH_CONVERSATIONS_PATH=/oh/conversations \
    OH_BASH_EVENTS_DIR=/oh/bash_events

RUN mkdir -p "${HOST_WORKSPACE_DIR}"

EXPOSE 7213

CMD ["uvicorn", "git_workspace_agent.server:app", "--host", "0.0.0.0", "--port", "7213"]
