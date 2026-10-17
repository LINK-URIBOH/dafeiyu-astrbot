# AstrBot 官方镜像 + 本项目需要的额外依赖
# ffmpeg 镜像里自带（/usr/bin/ffmpeg），另补两个 Python 包。
# 国内服务器用清华 pip 镜像；海外可去掉 -i 参数。
FROM soulter/astrbot:latest
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    edge-tts imageio-ffmpeg
