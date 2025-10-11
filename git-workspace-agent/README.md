# Git 工作区沙箱服务器

该目录提供一个独立的 FastAPI 服务：在 Docker 沙箱中启动 OpenHands 代理，并封装若干适用于 Git 仓库操作的 REST 接口。

## 环境要求

- 本地已运行 Docker
- 已设置环境变量 `LITELLM_API_KEY`
- 使用 `uv run` 初始化过的 Python 环境（参考项目根目录 README）

## 启动方式

```bash
uv run python git-workspace-agent/server.py
```

服务启动后访问 <http://localhost:8000/>，即可打开精简版 Web 控制台：

- 提交对话指令，可选输入 Git 仓库列表和访问令牌
- 实时查看 `/conversation` 返回的事件流
- 通过 ID 恢复既有工作区或会话

### API 速览

- `POST /conversation` — 新建/恢复会话，返回包含代理事件的 SSE 流
- `GET /workspace/{workspace_id}/conversations/{conversation_id}/events` — 输出已完成会话的事件归档
- `GET /workspace/{workspace_id}/conversations/{conversation_id}/state` — 获取缓存的基础状态
- `GET /workspace/{workspace_id}/project/file?file_path=` — 下载沙箱工作区内生成的文件

该 Web 控制台基于浏览器 Fetch 的流式读取实现，是集成 `/conversation` 接口时的最小参考实现。
