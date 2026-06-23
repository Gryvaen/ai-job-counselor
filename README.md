# AI 求职顾问

基于 **FastAPI + LangGraph + Ollama** 的求职 Agent。

用户输入求职目标后，Agent 按流水线执行：

```
岗位分析 → 技能缺口 → 学习路线 → 项目推荐
```

## 技术栈

- **FastAPI** — API 层
- **LangGraph** — 多节点 Agent 编排
- **Ollama** — 容器内 LLM + Tool Calling 结构化输出
- **Pydantic** — 请求/响应与 Tool schema 校验

## 快速开始

```bash
cp .env.example .env   # 按需修改 OLLAMA_MODEL
docker compose up --build -d
docker exec job-counselor-ollama ollama pull qwen2.5:7b
```

打开 http://localhost:8001

## API

```bash
curl -X POST http://localhost:8001/api/consult \
  -H "Content-Type: application/json" \
  -d '{"user_query": "我想找 AI Agent 实习", "resume_text": "Python, Docker"}'
```

## 架构

```text
用户输入
  ↓
FastAPI  POST /api/consult
  ↓
LangGraph StateGraph
  ├── JobAnalyzer        (extract_job_profile)
  ├── SkillGapAnalyzer   (analyze_skill_gap)
  ├── LearningPlanner    (build_learning_plan)
  └── ProjectRecommender (recommend_projects)
  ↓
Pydantic 结构化 JSON 响应
```

Ollama 不可用时自动降级为规则引擎 fallback。

## 环境变量

见 `.env.example`：

```env
OLLAMA_MODEL=qwen2.5:7b
WEBUI_API_TOKEN=
LOG_LEVEL=INFO
```

## 目录

```text
agent/       LangGraph 节点与流水线
api/         FastAPI + 静态前端
config/      配置与 LLM
models/      Pydantic 模型
tests/       单元与集成测试
```
