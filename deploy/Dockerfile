# AstrBot 官方镜像 + 本项目需要的额外依赖
# ffmpeg 镜像里自带（/usr/bin/ffmpeg），另补两个 Python 包。
# 国内服务器用清华 pip 镜像；海外可去掉 -i 参数。
# 钉版：已验证组合（v4.29.0 与本套补丁/插件适配）；升级时与 compose 的 NapCat tag 一起改
FROM soulter/astrbot:v4.29.0
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    edge-tts imageio-ffmpeg
