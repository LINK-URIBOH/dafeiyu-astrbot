FROM python:3.12-slim
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-noto-cjk ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
       browser-use==0.13.11 mcp==2.1.1 \
    && python -m pip check \
    && useradd --uid 10001 --create-home browser
WORKDIR /app
COPY server.py browser_allowlist.txt ./
USER 10001:10001
CMD ["python", "/app/server.py"]
