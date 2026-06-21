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
    BANK_DB_PATH=/app/data/bank.db
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
