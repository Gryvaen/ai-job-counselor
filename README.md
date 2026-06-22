# JobMatch Agent

基于 Boss 直聘的智能求职 Agent 系统：岗位采集 → RAG 知识增强 → 智能匹配 → 简历优化 → 飞书推送。

## 当前状态

项目已具备可运行的端到端闭环：

| 模块 | 状态 | 说明 |
|------|------|------|
| `config/` | ✅ | OpenAI / Chroma / Feishu / 路径统一配置 |
| `models/` | ✅ | Job, MatchResult, OptimizedResume, LearningPlan, AgentState |
| `scraper/` | ✅ | Playwright 爬虫，支持 cookie 登录持久化 |
| `storage/` | ✅ | SQLAlchemy SQLite 持久化 |
| `notifier/` | ✅ | 飞书 Webhook 消息推送 |
| `rag/` | ✅ | Chroma 向量检索 + OpenAI Embedding，已接入匹配证据 |
| `agent/` | ✅ | LangGraph StateGraph (plan → scrape → retrieve → match → optimize → review → notify → record) |
| `crews/` | ✅ 基础 | 简历优化与学习计划生成，保留证据/待核实标记 |
| `mcp_servers/` | ✅ | boss / rag / resume / optimizer / feishu 五个 MCP Server |

## 快速开始

### 1. 环境要求

- Python 3.11+ (当前项目使用 Python 3.14)
- 虚拟环境已在 `.venv/`

### 2. 安装依赖

```bash
.venv/bin/pip install playwright
.venv/bin/python -m playwright install chromium
```

> 注意：项目使用 `.venv/` 虚拟环境，所有命令请使用 `.venv/bin/python` 前缀。

### 3. 配置环境变量

复制 `.env.example` 为 `.env` 并填写：

```bash
cp .env.example .env
```

`.env` 文件内容：

```env
# OpenAI / 兼容 API
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# 飞书 Webhook（可选，不配置则跳过推送）
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

### 4. Boss 直聘登录

首次使用不再需要单独手动登录。运行流水线或进入 chat 后，如果本地没有可用登录态，Agent 会自动打开 Chromium 到 Boss 登录页，你只需要扫码登录一次，cookie 会保存到 `data/boss_state.json`，后续自动复用。

也可以提前运行登录辅助脚本：

```bash
.venv/bin/python scripts/login_boss.py
```

这会打开一个 Chromium 浏览器窗口，请在窗口中完成 Boss 直聘扫码/短信登录。

### 5. 准备简历主档案

复制简历模板并填写：

```bash
cp data/resume.json.template data/resume.json
```

`data/resume.json` 是你的**唯一事实来源**，系统不会自动修改此文件。参考格式：

```json
{
  "name": "张三",
  "skills": ["C", "Python", "Linux", "STM32"],
  "preferences": {
    "city": "上海",
    "target_roles": ["嵌入式", "BSP", "Linux驱动"],
    "keywords": ["Linux驱动", "BSP", "嵌入式软件"]
  }
}
```

### 6. 运行流水线

```bash
.venv/bin/python main.py run --keywords "Linux驱动,BSP" --city 上海
```

可选参数：

```bash
# 自定义匹配阈值
.venv/bin/python main.py run --keywords "Linux驱动,BSP" --city 上海 --threshold 80
```

**输出示例：**

```
[JOBMATCH] Running pipeline with keywords=['Linux驱动', 'BSP']
[agent/scrape] Searching for: ['Linux驱动', 'BSP']
[agent/match] Scored 12 jobs, 3 >= 75
[agent/notify] Sending alert for Linux BSP @ 芯联科技 (score=85)
[agent/notify] Notified 3 jobs via Feishu
[record_node] Saved 12 match results to data/jobmatch.db

=== Pipeline Results ===
Jobs scraped: 12
Matches scored: 12
Jobs notified: 3

  📌 Linux BSP 开发工程师 @ 芯联科技
    💰 15-25K | 📍 上海
    ⭐ Score: 85 | 推荐投递
    ✅ linux / 驱动 / bsp

  📌 嵌入式软件工程师 @ 智微电子
    💰 12-20K | 📍 深圳
    ⭐ Score: 78 | 推荐投递
    ✅ 嵌入式 / stm32 / arm
```

### 7. CLI 其他命令

```bash
# 交互命令模式
.venv/bin/python main.py chat

# chat 中可以直接说
帮我找上海的 Linux驱动,BSP 岗位 80分以上

# 或使用 Claude 风格 slash 指令
/search <城市> <关键词...> [80分以上]
/status
/help

# 查看某个岗位的匹配、RAG 证据、简历草稿和学习计划
.venv/bin/python main.py explain abc123
```

### 8. Web 操作台

启动本地前端工作台：

```bash
.venv/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000
```

Web 端支持：

- 输入技能、目标岗位、联系方式，生成 Markdown 简历模板
- 传入 GitHub 个人主页，自动读取公开仓库并转成项目经历证据
- 自动提示岗位能力缺口
- 一键复制/下载简历，生成版本保存到 `data/resume_versions/`

## 项目结构

```
ai_agent/
├── main.py                      # CLI 入口 (run/chat/explain)
├── config/settings.py           # Pydantic 统一配置
├── models/                      # Pydantic 数据模型
│   ├── job.py                   # Job 岗位模型
│   ├── match.py                 # MatchResult 匹配结果
│   ├── resume.py                # OptimizedResume / ResumeBullet
│   ├── optimizer.py             # LearningPlan 学习计划
│   └── agent_state.py           # AgentState LangGraph 状态
├── scraper/                     # Playwright 爬虫
│   ├── session.py               # 浏览器生命周期 + cookie 管理
│   ├── boss_scraper.py          # Boss 直聘搜索 + 去重
│   └── parser.py                # DOM 解析
├── storage/db.py                # SQLAlchemy SQLite 持久化
├── agent/                       # LangGraph 编排
│   ├── graph.py                 # StateGraph 定义
│   └── nodes/
│       ├── scrape_node.py       # 爬虫节点
│       ├── match_node.py        # 规则匹配节点
│       ├── notify_node.py       # 飞书通知节点
│       └── record_node.py       # 持久化节点
├── notifier/feishu.py           # 飞书 Webhook 推送
├── rag/                         # RAG (Phase 2)
│   ├── chunker.py               # 文档切分
│   ├── ingest.py                # 知识库入库
│   └── retriever.py             # Chroma 检索
├── scripts/
│   ├── login_boss.py            # Boss 登录辅助
│   └── ingest_knowledge.py      # RAG 知识库入库脚本
├── api/
│   ├── server.py                # FastAPI Web 操作台
│   └── static/                  # 前端页面、样式、交互
├── data/
│   ├── resume.json              # 简历主档案 (手动维护)
│   ├── resume.json.template     # 简历模板
│   ├── boss_state.json          # Playwright 登录态 (gitignore)
│   ├── jobmatch.db              # SQLite 数据库 (gitignore)
│   ├── knowledge/               # RAG 源文档目录
│   │   ├── projects/            # 项目文档
│   │   ├── notes/               # 学习笔记
│   │   ├── interviews/          # 面经
│   │   └── past_jobs/           # 历史 JD
│   └── resume_versions/         # 按岗位生成的定制简历
├── storage/vector_store/        # Chroma 向量索引 (gitignore)
├── tests/                       # 集成测试
│   ├── test_mock_pipeline.py    # Mock 流水线测试
│   ├── test_full_graph.py       # 完整 Graph 测试
│   └── test_notify_path.py      # 通知路径测试
├── pyproject.toml               # 项目依赖
├── .env.example                 # 环境变量模板
├── .gitignore                   # Git 忽略规则
└── docs/ARCHITECTURE.md         # 架构设计文档
```

## 流水线架构

```
plan → scrape → retrieve → match → (condition: score >= threshold?)
                              ├─ YES → optimize → review → notify → record
                              └─ NO  → record
```

- **scrape**: Playwright 搜索 Boss 直聘 → 提取 Job 列表 → 去重
- **retrieve**: 对每个岗位检索个人知识库，生成岗位级证据
- **match**: 结合搜索词、JD 关键词、简历技能、RAG 证据生成 MatchResult
- **optimize**: 为高分岗位生成定制简历草稿与学习计划
- **review**: 标记低置信度内容和 ATS 覆盖率风险
- **notify**: score >= threshold 的岗位推送飞书
- **record**: 岗位、匹配结果、简历草稿、学习计划写入 SQLite

## 集成测试

确认所有模块正常工作的 3 个集成测试：

```bash
.venv/bin/python tests/test_mock_pipeline.py   # Mock 数据 → 匹配 → 存储
.venv/bin/python tests/test_full_graph.py      # 完整 LangGraph 流程
.venv/bin/python tests/test_notify_path.py     # 验证 notify 分支被触发
```

## Docker + Ollama 本地模型

项目提供 `docker-compose.yml`，默认只启动 JobMatch WebUI，并复用你已有的 Ollama 容器。

- `webui`: JobMatch WebUI，默认暴露到 `http://127.0.0.1:8000`
- `ollama`: 复用外部容器，要求 WebUI 加入 Ollama 所在 Docker 网络

首次启动：

```bash
cp .env.example .env
docker compose up -d --build
```

如果你的 Ollama 来自 Open WebUI 的 compose，通常网络名是 `open-webui_default`，`.env` 保持：

```env
OLLAMA_DOCKER_NETWORK=open-webui_default
OLLAMA_BASE_URL=http://ollama:11434/v1
```

在已有 Ollama 容器中拉取推荐模型：

```bash
docker exec ollama ollama pull qwen2.5:7b
docker exec ollama ollama pull nomic-embed-text
```

在 WebUI 的「设置」页选择：

```text
模型提供商: 本地 Ollama
Ollama Base URL: http://ollama:11434/v1
Ollama Chat Model: qwen2.5:7b
Ollama Embedding Model: nomic-embed-text
```

常用命令：

```bash
docker compose logs -f webui
docker compose restart webui
docker compose down
```

## 开发计划

| 阶段 | 目标 | 交付物 |
|------|------|--------|
| Phase 1 (✅ 已完成) | 采集 + 基础匹配 + 飞书推送 + SQLite | 端到端管线 |
| Phase 2 (✅ 已完成) | RAG 增强匹配 | retrieve_node 接入 match_node |
| Phase 3 (✅ 已完成) | LangGraph 全流程 + MCP Server | 5 个 MCP Server + chat/explain 模式 |
| Phase 4 (✅ 基础完成) | 简历优化 + 学习计划 | optimize_node + review_node + 版本管理 |

## 安全注意

- `.env`、`boss_state.json`、`jobmatch.db` **不得提交到 git**（已在 `.gitignore`）
- Boss 直聘采集仅限个人求职用途，建议每日 1-2 次
- 简历主档案 (`data/resume.json`) **永不由 Agent 自动覆盖**
- 所有密钥通过环境变量注入，不写死在代码中
