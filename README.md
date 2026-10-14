# 🐋 大肥鱼 · AstrBot QQ 机器人全家桶

> 一只住在 QQ 里的蓝色鲸鱼娘：会看、会听、会说话、有记忆、会主动找你，
> 还会嘴硬地催你吃饭。基于 **AstrBot + NapCat + DeepSeek + 阿里云百炼** 搭建。

大肥鱼是 DeepSeek 蓝鲸 logo 的**社区二创形象**（非官方），本项目把「让她住进 QQ 里」
的全套实践开源出来：一个高完成度的 AstrBot 插件、一套完整人格、以及踩过所有坑的实录。

## ✨ 能力清单

| 感官 | 能力 | 实现 |
|---|---|---|
| 👁️ 看 | 图片 / 表情包 / 视频（目前只能读前16秒的画面） | qwen3-vl 转述 + ffmpeg 抽帧 |
| 🎧 听 | 语音消息 / 视频音轨（目前只能捕捉60秒的音频）| NapCat 转码 + qwen3-asr-flash |
| 🔊 说 | 语音条（含自定义音色） | 百炼音色复刻 + qwen-audio-3.1-tts-flash |
| 😀 表情 | 真 QQ 表情（326 张脸） | 自研插件把 `[旺柴]` 变成真实表情段 |
| 🧠 记 | 长期记忆 | livingmemory + 本地 Ollama bge-m3 嵌入 |
| 📲 主动 | 随机 + 沉默触发 | proactive_chat |
| 🛡️ 防护 | 白名单 / 防注入 / 草稿箱 | 多层设计，见踩坑合集 |

## 📦 内容

```
plugin/astrbot_plugin_face_convert/   ← 核心插件（AstrBot 插件，直接可装）
persona/大肥鱼-人格.md                 ← 人格提示词（可直接导入 AstrBot）
persona/课程记忆-模板.md               ← "让她自己悟"的教学记忆模板
docs/部署指南.md                       ← 从零搭建的路线图
docs/踩坑合集.md                       ← ⭐ 最有价值的部分：所有坑与解法
```

## 🚀 快速开始

1. 按 `docs/部署指南.md` 搭好 AstrBot + NapCat + QQ 小号
2. 把 `plugin/astrbot_plugin_face_convert/` 放进 AstrBot 的 `data/plugins/`
   （插件会自动读取你 AstrBot 配置里的 DashScope key，用于语音/视频理解）
3. 在 AstrBot 里新建人格，粘贴 `persona/大肥鱼-人格.md` 正文
4. 重启，开聊 🎉

## 🔌 插件做了什么

`astrbot_plugin_face_convert` 是一个「出站整形 + 入站翻译」双通道插件：

**出站（她说什么）**
- `[旺柴]` `[吃瓜]` 等中括号表情名 → **真正的 QQ 表情段**（QQ 不会渲染机器人发的纯文本表情码）
- 草稿箱：双层括号 `（（ ））` 里的内容会被撕掉（给她一个"自己咽回去"的出口）
- 三道轻量橡皮擦：嘴硬小尾巴 / meta 口癖句 / 表情冷却（可逐道关闭，见源码顶部）

**入站（她看到什么）**
- 纯表情消息的文本是空的，会被上游当"空消息"跳过 → 翻译成 `[旺柴]` 文本
- 图片 / 表情包 → 补上"[对方发来一张图片]"，交给 AstrBot 的图片转述
- 语音 → NapCat 转 mp3 → qwen3-asr-flash 听写 → 文本进上下文
- 视频 → 本地下载 → ffmpeg 抽帧 + 抽音轨 → qwen3-vl 逐帧描述 + qwen3-asr 听声

## 🙏 致敬与出处

- **大肥鱼**：DeepSeek 蓝鲸的社区二创（"你这只吃白饭的蓝色大肥鱼"梗），非官方角色
- 角色设定规范参考社区项目 [YunYueSama/codex-deepseek-pet](https://github.com/YunYueSama/codex-deepseek-pet)
- 依赖生态：[AstrBot](https://github.com/AstrBotDevs/AstrBot) · [NapCat](https://github.com/NapNeko/NapCatQQ) · [livingmemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory) · [proactive_chat](https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat)

## 📄 License

MIT（见 LICENSE）。人格文本与插件代码可自由使用，转载注明出处即可。

