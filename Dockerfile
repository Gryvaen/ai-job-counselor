# 使用官方 Python 3.11 精简版作为基础镜像（体积极小，无多余依赖）
FROM python:3.11-slim

# 设置环境变量
# PYTHONDONTWRITEBYTECODE: 防止生成 pyc 字节码
# PYTHONUNBUFFERED: 日志及时输出到控制台
# PIP_NO_CACHE_DIR: 安装依赖时不缓存 wheel，减小镜像体积
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 设置工作目录（所有接下来命令都在 /app 目录执行）
WORKDIR /app

# 安装必要的系统依赖，只装 curl 和 CA 证书，并删除 apt 缓存缩小镜像体积
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 复制 requirements、pyproject、README 到容器中，方便后续依赖安装和包构建
COPY requirements.txt pyproject.toml README.md ./

# 升级 pip，然后安装依赖，--no-deps . 只安装当前目录包，不递归安装依赖，依赖已提前装好
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install --no-deps .

# 复制项目核心代码到容器内，保证应用代码可用
COPY agent ./agent
COPY api ./api
COPY config ./config
COPY models ./models

# 开放容器 8001 端口用于 web 服务
EXPOSE 8001

# 健康检查，每 30s 检查一次服务接口 /api/health 是否健康（最大重试 3 次），超时时间 10s，启动延时 20s
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8001/api/health || exit 1

# 启动命令，运行 Uvicorn 服务器，监听 0.0.0.0:8001，入口是 api.server:app
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8001"]
