# AI Agent Interview Bot

面向 AI Agent 岗位的模拟面试机器人。项目保留简历档案、JD 分析和 RAG 证据检索能力，但主体验已经重构为：候选人档案 → AI Agent 技术栈多轮面试 → 结构化反馈 → 能力覆盖检查。

## 为什么这样设计

AI Agent 岗位面试会集中考察“能不能把 LLM 应用做成可靠产品”，不只是会调 API。这个版本把相关技术拆成可追问、可评分、可复盘的面试能力域：

- LLM / Prompt / Function Calling
- LangGraph / Planner-Executor / 多 Agent 编排
- RAG、Embedding、向量数据库、Rerank 与引用证据
- 工具调用、MCP 风格工具边界、权限、超时和重试
- 短期记忆、长期记忆、上下文压缩和隐私策略
- Eval、Guardrail、幻觉检测、Prompt 注入防护
- FastAPI、SQLite、Chroma、Docker、监控、CI/CD 等工程化能力

## 快速开始

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m uvicorn api.server:app --reload
```

打开 `http://127.0.0.1:8000`。

## 使用流程

1. 在“候选人档案”填写目标岗位、技能栈、项目经历和 GitHub 亮点。
2. 生成 Markdown 档案，作为后续模拟面试上下文。
3. 进入“Agent 面试”，启动多轮面试。
4. 每轮回答后查看反馈、评分标准、答题结构和能力覆盖情况。
5. 根据缺口补充项目证据、学习计划或重新训练回答。

## CLI

```bash
.venv/bin/python main.py run --keywords "AI Agent,LangGraph,Python" --city 上海 --threshold 80
```

CLI 会从本地岗位库读取命中的 JD，并执行与 WebUI 相同的匹配流程。

## 目录

```text
agent/                 LangGraph 节点和主流程
api/                   FastAPI Web 控制台
config/                配置与 LLM Provider
crews/                 简历优化、学习计划生成逻辑
models/                Pydantic 数据模型
rag/                   文档切分、入库、检索
scripts/               知识库入库、数据备份脚本
storage/               SQLite 表结构与持久化工具
tests/                 端到端和节点测试
```

## 环境变量

常用配置可写入 `.env`：

```env
MODEL_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
RESUME_PATH=data/resume.json
KNOWLEDGE_DIR=data/knowledge
RESUME_VERSIONS_DIR=data/resume_versions
DB_PATH=data/jobmatch.db
CHROMA_DIR=storage/vector_store
MATCH_THRESHOLD=75
```

## 安全边界

- 不自动投递、不批量私信、不绕过平台限制。
- `.env`、`data/jobmatch.db`、个人简历数据不要提交到公开仓库。
- 岗位 JD 建议来自手动粘贴、公开 JD 文本、朋友内推说明或自己维护的职位清单。
