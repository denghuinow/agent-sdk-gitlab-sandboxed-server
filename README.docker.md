# Git Workspace Agent Docker 部署指南

该方案利用 Docker 构建并运行 `git_workspace_agent/server.py`，同时保留 OpenHands 沙箱所需的 Docker 访问能力。

## 先决条件

- 主机已安装 Docker（建议版本 ≥ 24），并允许当前用户访问 `/var/run/docker.sock`。
- 准备好有效的 LLM Key（`LITELLM_API_KEY`）以及可选的 Git 访问令牌。

## 构建镜像

```bash
docker compose build
```

> 如需离线构建或定制依赖，可直接运行 `docker build -t git-workspace-agent .`。

## 运行服务

默认映射

```bash
docker compose up
```

将会：

- 监听 `http://localhost:7213`
- 在主机 `/tmp/git-workspace-agent` 下持久化工作区
- 将宿主 Docker 套接字挂载给容器，以便沙箱再起子容器

### 自定义工作区位置

OpenHands 沙箱运行时会通过 Docker CLI 再启动内层容器，对卷挂载路径非常敏感，必须保持**主机与容器看到的绝对路径一致**。建议按以下方式在运行前设置：

```bash
export HOST_WORKSPACE_DIR="$(pwd)/data"
mkdir -p "${HOST_WORKSPACE_DIR}"
docker compose up
```

Compose 文件会自动把该目录绑定到容器的同一路径，并在内部作为 `HOST_WORKSPACE_DIR` 使用，保证沙箱挂载不会失败。

## 环境变量

项目根目录提供了 `.env` 示例，可根据需求调整后直接被 `docker compose` 加载：

- `LITELLM_API_KEY`（必填）：主模型的访问密钥
- `LLM_MODEL` / `LLM_BASE_URL`：模型以及 API 兼容层
- `OH_*`：控制沙箱内部的持久化目录，通常保持默认即可

> `.env` 含有敏感信息，不要提交到版本库。

## 常用操作

- 首次运行：`docker compose up --build`
- 后台运行：`docker compose up -d`
- 查看日志：`docker compose logs -f`
- 停止服务：`docker compose down`

## 故障排查

- **启动失败并提示 `Docker 未运行`**：确保宿主 Docker 服务已启动，并且 `docker compose` 运行用户拥有访问 `/var/run/docker.sock` 的权限。
- **沙箱容器启动时报 “mount path not found”**：检查 `HOST_WORKSPACE_DIR` 是否设置成宿主可见的绝对路径，并确认该路径已经在宿主创建。
- **缺少依赖或镜像拉取太慢**：可修改 `Dockerfile` 中的基础镜像或预先拉取 `ghcr.io/all-hands-ai/agent-server:latest-python`。
