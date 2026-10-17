# ☁️ 云上安家 · Docker 部署套件

> 把大肥鱼从 Windows 桌面搬进一台 Linux 云服务器，7×24 在线。
> 本目录是这次迁移沉淀下来的可复用套件（已在 2C4G / Ubuntu 24.04 实弹演练）。

## 架构

```
QQ 用户 ⇄ 腾讯服务器 ⇄ NapCat(Docker) ⇄ WebSocket(6199) ⇄ AstrBot(Docker) ⇄ DeepSeek / 百炼 / 硅基流动
```

- 两个容器在同一个 compose 网络里，NapCat 通过 `ws://astrbot:6199/ws` 反向连接 AstrBot
- 两个核心补丁（TTS WebSocket、TTS 表情过滤）用 **bind-mount** 接入容器，
  升级镜像不丢补丁
- 嵌入 provider 从本地 Ollama 切到**硅基流动 bge-m3**（同模型，向量余弦 0.9999+，零重嵌）

## 目录约定

```
/opt/dafeiyu/
├── compose.yaml        # 编排（基于本目录的 compose）
├── Dockerfile          # 官方镜像 + edge-tts / imageio-ffmpeg
├── patches/            # 两个核心补丁（从旧机 core 提取）
├── astrbot/data/       # 旧机 core/data（排除 temp / logs / *.bak_*）
├── napcat/config|qq/   # NapCat 配置与登录态
├── backups/            # 每日滚动备份
└── incoming/           # 迁移时的一次性上传暂存
```

## 迁移步骤（要点）

1. **旧机停服**：先停看门狗，再停 AstrBot / NapCat（避免同 QQ 双登互踢），
   然后打包 `core/data`（排除 `temp` / `logs` / `*.bak_*`，26MB 左右）
2. **服务器**：装 Docker；国内拉镜像需配置 registry mirror（如 `docker.1panel.live`，
   以当时可用为准）
3. **构建镜像**：`docker compose build`（补 edge-tts / imageio-ffmpeg）
4. **起 AstrBot** → 灌数据 → 起 NapCat → 打开 WebUI（6099 端口）扫码登录小号
5. **切嵌入**：运行 `apply_sf_embedding.py`（自动从插件配置读 key，幂等）
6. **安全组**：开放 6185（AstrBot 面板）与 6099（NapCat WebUI）
7. **备份**：`backup.sh` + cron；另可用本地脚本定期把最新备份拉回电脑

## 踩过的坑

- **QQ 登录态不可跨平台迁移**：Linux NapCat 必须重新扫码一次
- **双登互踢**：旧机自启项（AstrBot Launcher / 启动大肥鱼QQ）务必停用
- **升级覆盖补丁**：核心补丁不要改镜像，bind-mount 挂进去
- **嵌入别重跑**：同款 bge-m3 的向量互相兼容，不需要重建索引
  （验证法：取一条旧向量与云端新嵌入算余弦，≈1 即可）
- `data/` 里可能混着旧机的 `site-packages` 残留，可忽略
