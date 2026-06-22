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
- 粘贴过往简历、项目经历、Markdown 或 JSON，生成新的 `data/resume.json` 简历事实档案
- **设置页「重建知识库索引」**：将 `data/knowledge/` 入库到 Chroma
- 在对话助手输入 `/search <城市> <岗位关键词> [分数]`，可视化查看解析、Boss 搜索、RAG 检索、匹配、简历生成、复核、保存全过程
- 在匹配结果中按不同公司和岗位生成对应的定制简历版本
- 自动提示岗位能力缺口
- 一键复制/下载简历，生成版本保存到 `data/resume_versions/`

### 9. 知识库入库（RAG 必做）

将项目文档、笔记放入 `data/knowledge/` 子目录后执行：

```bash
.venv/bin/python scripts/ingest_knowledge.py
```

或在 WebUI **设置 → 重建知识库索引**。

### 10. 定时自动搜索（cron）

```bash
# 每天早上 8 点（需配置 WEBUI_API_TOKEN 时加 Authorization 头）
0 8 * * * curl -fsS -X POST -H "Authorization: Bearer $WEBUI_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"keywords":"Linux驱动,BSP","city":"上海","threshold":80}' \
  http://127.0.0.1:8000/api/run
```

也可使用 CLI：`python main.py run --keywords "Linux驱动,BSP" --city 上海`

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

## WebUI 工作流

1. 在「我的简历」粘贴用户过往项目、原始简历、Markdown 或 JSON，点击「生成事实档案」。系统会解析姓名、联系方式、技能、项目、经历和教育信息，并写入 `data/resume.json`。
2. 在「对话助手」输入 `/search 上海 AI Agent Python 80分以上`，或在「岗位搜索」表单提交关键词。后台任务会展示每个阶段的实时进度。
3. 搜索完成后进入「匹配结果」，查看每个岗位的分数、优势、缺口和 RAG 证据。
4. 对不同公司和岗位点击「生成定制简历」，系统会使用同一份事实档案生成岗位专属 Markdown 版本，并保存到 `data/resume_versions/` 和 SQLite。

## 模块职责

| 路径 | 作用 |
|------|------|
| `api/server.py` | FastAPI 后端，负责 WebUI API、配置保存、简历导入、后台搜索任务、chat slash 指令和结果查询 |
| `api/static/` | 原生 HTML/CSS/JS 前端，提供仪表盘、对话助手、简历档案、搜索进度、匹配详情和设置页 |
| `agent/graph.py` | LangGraph 主编排，把 plan/scrape/retrieve/match/optimize/review/notify/record 串成完整流水线 |
| `agent/nodes/` | 单个 Agent 节点实现，每个节点只处理一个阶段的状态更新 |
| `scraper/` | Playwright Boss 直聘浏览器自动化、登录态复用、岗位列表和详情解析 |
| `rag/` | 知识库切分、入库和 Chroma 检索，为匹配解释提供个人项目证据 |
| `crews/` | 简历优化和学习计划生成逻辑，基于 `resume.json` 事实档案，不主动编造经历 |
| `models/` | Pydantic/状态模型，定义 Job、MatchResult、OptimizedResume、LearningPlan 和 AgentState |
| `storage/db.py` | SQLite 表结构和持久化 helper，保存岗位、匹配、简历版本、学习计划和通知记录 |
| `mcp_servers/` | MCP Server 适配层，把 Boss/RAG/Resume/Optimizer/Feishu 能力暴露给兼容客户端 |
| `notifier/` | 飞书 Webhook 通知封装 |
| `config/` | `.env` 和路径配置读取，支持 OpenAI 兼容 API 与本地 Ollama |
| `scripts/` | Boss 登录、知识库入库等辅助脚本 |
| `data/` | 本地运行数据，包含简历事实档案模板、登录态、知识库源文档和生成的简历版本 |
| `tests/` | Mock 流水线、完整 Graph 和通知分支的集成测试 |

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
- Boss 直聘采集仅限个人求职用途，建议每日 1-2 次（`SCRAPE_COOLDOWN_HOURS` 默认 24h）
- 简历主档案 (`data/resume.json`) 只会在用户明确保存表单或点击「生成事实档案」时覆盖
- 所有密钥通过环境变量注入，不写死在代码中
- 公网/VPS 暴露时设置 `WEBUI_API_TOKEN`；`GET /api/config` 已对密钥脱敏

## 个人生产版部署检查清单

- [ ] `.env` 已配置（模型、飞书、可选 `WEBUI_API_TOKEN`）
- [ ] `data/resume.json` 已填写事实档案
- [ ] `data/knowledge/` 有内容且已执行 ingest（脚本或 WebUI）
- [ ] Boss 登录态有效（`/api/health` → `boss_login_exists: true`）
- [ ] `/api/health` 子检查通过（database / chroma / ollama）
- [ ] 手动跑通一次 `/search` 全链路
- [ ] `scripts/backup_data.sh` 已加入 cron（建议每日）
- [ ] Docker `healthcheck` 绿色（若使用 compose）
- [ ] uvicorn 监听 `127.0.0.1` 或反代 + Bearer token

## 数据备份

```bash
./scripts/backup_data.sh
# 归档写入 backups/YYYYMMDD_HHMMSS.tar.gz，自动保留最近 14 份
```

cron 示例：`0 3 * * * /path/to/ai_agent/scripts/backup_data.sh`

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```
