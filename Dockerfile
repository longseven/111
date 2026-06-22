# K12 数学题目改编系统 —— 容器镜像
# pandoc 由 pypandoc-binary 随包自带二进制，matplotlib/pillow 用 manylinux 轮子，
# 因此 slim 基础镜像无需额外 apt 依赖即可构建。
FROM python:3.11-slim

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再拷源码
COPY app ./app
COPY static ./static

# 运行时数据（题库 SQLite + 在线设置覆盖）落在挂载卷里，重建容器不丢
ENV CONFIG_PATH=/app/data/runtime.json \
    BANK_DB_PATH=/app/data/bank.db \
    WEB_CONCURRENCY=2 \
    LLM_MAX_CONCURRENCY=4

VOLUME ["/app/data"]

EXPOSE 8000

# 多 worker 提升并发吞吐（WEB_CONCURRENCY 控制进程数）。
# 总出站并发 ≈ WEB_CONCURRENCY × LLM_MAX_CONCURRENCY，按代理额度调。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
