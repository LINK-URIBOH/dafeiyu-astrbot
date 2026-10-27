FROM soulter/astrbot:v4.29.0
COPY vendor/plugins/ /opt/dafeiyu-plugin-sources/
RUN python -m pip freeze | grep -E '^[A-Za-z0-9_.-]+==' > /tmp/astrbot-base-constraints.txt \
    && find /opt/dafeiyu-plugin-sources -maxdepth 2 -name requirements.txt -print \
       | sort | sed 's|^|-r |' > /tmp/plugin-requirements.txt \
    && python -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
       -c /tmp/astrbot-base-constraints.txt -r /tmp/plugin-requirements.txt \
       edge-tts imageio-ffmpeg dashscope \
    && python -m pip check
