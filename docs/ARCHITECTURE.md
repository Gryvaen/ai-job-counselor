# Architecture

JobMatch Agent 是一个本地优先的求职 Agent 工作台，目标是展示 AI Agent 工程能力，而不是招聘平台自动化采集能力。

## Pipeline

```text
plan -> source -> retrieve -> match -> optimize -> review -> record
```

- `plan`: 从自然语言或表单解析关键词、城市、匹配阈值。
- `source`: 从 SQLite 本地岗位库读取 JD，不访问招聘平台。
- `retrieve`: 以岗位 JD 为 query，从个人知识库检索项目、经历、技能证据。
- `match`: 生成匹配分、优势、缺口和推理说明。
- `optimize`: 对高匹配岗位生成定制简历和学习计划。
- `review`: 复核草稿，标出 ATS 覆盖和待核实内容。
- `record`: 保存岗位、匹配结果、简历版本和学习计划。

## Runtime Components

```text
WebUI / CLI
   |
FastAPI task runner
   |
LangGraph pipeline
   |
SQLite + Chroma + LLM Provider
```

## Data Stores

- SQLite: 岗位库、匹配结果、简历版本、学习计划、异步任务。
- Chroma: 个人知识库向量索引。
- `data/resume.json`: 简历事实档案。
- `data/resume_versions/`: 针对岗位生成的 Markdown 简历版本。

## 展示重点

- 可解释的岗位匹配，而不是黑盒关键词过滤。
- RAG 证据链，把“我会什么”落到项目事实。
- 面向真实投递的定制简历与学习计划。
- 异步任务状态、持久化、配置管理等工程化能力。

## Removed Scope

项目不再包含招聘平台自动化采集、登录态管理、浏览器采集或风控绕过逻辑。岗位来源由用户手动导入或从已有本地数据读取。
