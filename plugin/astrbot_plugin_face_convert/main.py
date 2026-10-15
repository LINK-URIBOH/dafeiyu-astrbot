"""把 LLM 回复中的 [表情名] 文字自动转换成真实 QQ 表情段。

原理：QQ 只在"人手输入"时把 [旺柴] 这类文字渲染成表情，
机器人发出的纯文本接收端只会看到字面量。本插件在消息发送前
把 [名字] 替换为真正的 face 消息段（NapCat / OneBot v11）。
字典来源：NapCat 内置 qface 表 + 社区 315 条 sysface 快照合并（414 条）。
"""

import asyncio
import json
import os
import re
import tempfile
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import At, Face, Image, Plain, Record, Reply, Video
from astrbot.core.star.session_llm_manager import SessionServiceManager

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_REPLACE = 8  # 单条消息最多替换几个表情，防刷屏


@register(
    "astrbot_plugin_face_convert",
    "dafeiyu-tools",
    "把 LLM 回复中的 [流泪][doge] 等文字表情自动转换为真实 QQ 表情段",
    "1.1.0",
)
class FaceConvertPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        map_path = os.path.join(PLUGIN_DIR, "face_map.json")
        with open(map_path, encoding="utf-8") as f:
            self.face_map: dict[str, int] = json.load(f)
        # 反向表：id -> 名字（用于把收到的表情翻译成文字喂给 LLM）
        self.id2name: dict[int, str] = {}
        for name, fid in self.face_map.items():
            self.id2name.setdefault(fid, name)
        # 手工优先级：通称覆盖
        self.id2name[277] = "旺柴"
        self.id2name[179] = "doge"
        self.pattern = re.compile(r"\[([^\[\]]{1,8})\]")
        # 表情冷却：记录她最近用过哪些脸的 id（治"又发好多狗头"）
        self._recent_faces: list[int] = []
        # DashScope key（用于语音转写）+ 管理员名单（群聊里标成「主人」）
        self.dashscope_key = ""
        self.admins: list[str] = []
        try:
            cfg_path = os.path.abspath(
                os.path.join(PLUGIN_DIR, "..", "..", "cmd_config.json")
            )
            with open(cfg_path, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            for prov in cfg.get("provider", []):
                if prov.get("id") == "dashscope_tts" and prov.get("api_key"):
                    self.dashscope_key = prov["api_key"]
                    break
            self.admins = [str(a).strip() for a in (cfg.get("admins_id") or [])]
        except Exception as e:
            logger.warning(f"[face_convert] 读取 DashScope key 失败: {e}")
        logger.info(
            f"[face_convert] 表情字典载入完成，共 {len(self.face_map)} 条；"
            f"语音转写{'已就绪' if self.dashscope_key else '未配置'}"
        )

    async def _transcribe_voice(self, event: AstrMessageEvent, rec) -> str | None:
        """语音消息 -> 文字：NapCat 转 mp3 -> 百炼 qwen3-asr-flash"""
        if not self.dashscope_key:
            return None
        try:
            file_ref = getattr(rec, "file", None) or getattr(rec, "url", None) or getattr(rec, "path", None)
            if not file_ref:
                return None
            # 1) 让 NapCat 把语音转成 mp3（它自带 silk 解码）
            try:
                resp = await event.bot.get_record(file=file_ref, out_format="mp3")
            except Exception:
                resp = await event.bot.get_record(file=file_ref)
            mp3 = None
            if isinstance(resp, dict):
                mp3 = (resp.get("data") or {}).get("file") or resp.get("file")
            if not mp3:
                return None
            # 2) 解析到本地文件
            path = str(mp3).replace("file:///", "").replace("file://", "")
            if path.startswith("http"):
                import aiohttp
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(path, timeout=aiohttp.ClientTimeout(total=30)) as r:
                        body = await r.read()
                tmp = os.path.join(tempfile.gettempdir(), f"asr_{int(time.time()*1000)}.mp3")
                with open(tmp, "wb") as f:
                    f.write(body)
            else:
                tmp = path
            # 3) 转写
            return await self._asr_file(tmp)
        except Exception as e:
            logger.warning(f"[face_convert] 语音转写失败: {str(e)[:150]}")
            return None

    @staticmethod
    def _extract_text(resp) -> str | None:
        """从 DashScope 多模态返回里抽出文本。"""
        try:
            out = getattr(resp, "output", None)
            choices = (getattr(out, "choices", None) or []) if out else []
            for ch in choices:
                msg = getattr(ch, "message", None)
                content = getattr(msg, "content", None) if msg else None
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("text"):
                            return str(item["text"]).strip()
        except Exception:
            pass
        return None

    async def _mm_call(self, model: str, content_items: list, timeout: int = 60) -> str | None:
        """统一的多模态调用（本地文件自动上传）。"""
        import dashscope
        from dashscope.aigc.multimodal_conversation import MultiModalConversation

        dashscope.api_key = self.dashscope_key

        def _call():
            return MultiModalConversation.call(
                model=model,
                messages=[{"role": "user", "content": content_items}],
            )

        loop = asyncio.get_running_loop()
        r = await asyncio.wait_for(loop.run_in_executor(None, _call), timeout=timeout)
        return self._extract_text(r)

    async def _asr_file(self, path: str) -> str | None:
        """本地音频文件 -> 文字（qwen3-asr-flash）。"""
        return await self._mm_call(
            "qwen3-asr-flash", [{"audio": f"file:///{path.replace(os.sep, '/')}"}]
        )

    async def _vl_describe(self, path: str) -> str | None:
        """本地图片 -> 一句话描述（qwen3-vl-plus）。"""
        return await self._mm_call(
            "qwen3-vl-plus",
            [
                {"image": f"file:///{path.replace(os.sep, '/')}"},
                {"text": "这是视频的一帧截图。用一句短话（30字内）描述画面内容，直接说内容，不要客套。"},
            ],
        )

    @staticmethod
    def _ffmpeg_exe() -> str | None:
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            import shutil

            return shutil.which("ffmpeg")

    async def _download_ok(self, url: str, tmpdir: str) -> str | None:
        """下载并做防伪检查（避免下到报错网页）。成功返回本地路径。"""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                    body = await r.read()
            logger.info(f"[face_convert] 下载 {len(body)}B 头部={body[:12]!r}")
            if len(body) < 1000 or body[:12].lstrip().startswith(b"<"):
                return None
            vf = os.path.join(tmpdir, "in.mp4")
            with open(vf, "wb") as f:
                f.write(body)
            return vf
        except Exception as e:
            logger.info(f"[face_convert] 下载失败: {str(e)[:80]}")
            return None

    async def _resolve_video(self, event: AstrMessageEvent, comp, tmpdir: str) -> str | None:
        """把视频字段解析成本地文件（多候选兜底：url -> 路径 -> 凭单号找 NapCat 要）。"""
        file_f = getattr(comp, "file", None)
        url_f = getattr(comp, "url", None)
        path_f = getattr(comp, "path", None)
        logger.info(
            f"[face_convert] 视频字段: file={str(file_f)[:70]!r} "
            f"url={str(url_f)[:70]!r} path={str(path_f)[:70]!r}"
        )
        cands = []
        for f in (url_f, path_f, file_f):
            if f and str(f).strip() and str(f).strip() not in cands:
                cands.append(str(f).strip())
        for cand in cands:
            p = cand.replace("file:///", "").replace("file://", "")
            if p.startswith("http"):
                vf = await self._download_ok(p, tmpdir)
                if vf:
                    return vf
            elif os.path.exists(p):
                return p
            else:
                # 光杆文件名 -> 凭单号找 NapCat 提货
                try:
                    resp = await event.bot.get_file(file=cand)
                    d = resp.get("data") if isinstance(resp, dict) else None
                    rp = None
                    if isinstance(d, dict):
                        rp = d.get("file") or d.get("path") or d.get("url")
                    if not rp and isinstance(resp, dict):
                        rp = resp.get("file") or resp.get("url")
                    if rp:
                        rp = str(rp).replace("file:///", "").replace("file://", "")
                        logger.info(f"[face_convert] NapCat 提货: {rp[:90]}")
                        if rp.startswith("http"):
                            vf = await self._download_ok(rp, tmpdir)
                            if vf:
                                return vf
                        elif os.path.exists(rp):
                            return rp
                except Exception as e:
                    logger.info(f"[face_convert] get_file({cand[:40]}) 失败: {str(e)[:80]}")
        return None

    async def _process_video(self, event: AstrMessageEvent, comp) -> str:
        """视频 -> 画面描述 + 声音转写。"""
        tmpdir = None
        try:
            tmpdir = tempfile.mkdtemp(prefix="vid_")
            video = await self._resolve_video(event, comp, tmpdir)
            if not video:
                logger.info("[face_convert] 视频解析失败：所有候选都没提到货")
                return "（没看清）"
            ff = self._ffmpeg_exe()
            if not ff:
                return "（没看清）"
            # 抽帧：前 16 秒、每 4 秒一帧，最多 4 帧
            proc = await asyncio.create_subprocess_exec(
                ff, "-y", "-i", video, "-t", "16", "-vf", "fps=1/4",
                "-frames:v", "4", "-q:v", "3",
                os.path.join(tmpdir, "f_%02d.jpg"),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                logger.warning(f"[face_convert] 抽帧失败 rc={proc.returncode}: {err[-260:].decode('utf-8', 'ignore')}")
            # 音轨：前 60 秒转 16k 单声道 mp3
            audio = os.path.join(tmpdir, "a.mp3")
            proc = await asyncio.create_subprocess_exec(
                ff, "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-t", "60",
                audio,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                logger.warning(f"[face_convert] 抽音轨失败 rc={proc.returncode}: {err[-260:].decode('utf-8', 'ignore')}")
            # 逐帧看图（最多留 3 条不同描述）
            descs = []
            for i in range(1, 5):
                fp = os.path.join(tmpdir, f"f_{i:02d}.jpg")
                if not os.path.exists(fp):
                    break
                d = await self._vl_describe(fp)
                if d and len(d) > 1 and d not in descs:
                    descs.append(d)
                if len(descs) >= 3:
                    break
            # 听声音
            said = None
            if os.path.exists(audio) and os.path.getsize(audio) > 2000:
                said = await self._asr_file(audio)
            logger.info(f"[face_convert] 视频解读: 帧描述={len(descs)}条, 声音转写={'有' if said else '无'}")
            parts = []
            if descs:
                parts.append("画面是：" + "；".join(descs))
            if said:
                parts.append("声音里说的是：" + said)
            return "；".join(parts) if parts else "（没看清也没听清）"
        except Exception as e:
            logger.warning(f"[face_convert] 视频处理失败: {str(e)[:150]}")
            return "（没看清）"
        finally:
            if tmpdir:
                import shutil as _sh

                _sh.rmtree(tmpdir, ignore_errors=True)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def inbound_face_to_text(self, event: AstrMessageEvent):
        """把收到的 QQ 表情翻译成 [名字] 文本。

        纯表情消息的 message_str 为空，上游会当"空消息"处理导致她装死不回；
        这里把表情名拼进文本，让整条链路正常运转。
        """
        try:
            comps = event.get_messages()
        except Exception:
            return
        # 验尸记录仪：遇到不认识的组件类型就备案（排查神秘消息用）
        known = (Face, Image, Record, Video, Plain)
        unknown = [type(c).__name__ for c in comps if not isinstance(c, known)]
        if unknown:
            logger.info(f"[face_convert] 未知消息组件: {unknown}")
        names = []
        img_count = 0
        recs = []
        vids = []
        for c in comps:
            if isinstance(c, Face):
                names.append(f"[{self.id2name.get(c.id, f'表情{c.id}')}]")
            elif isinstance(c, Image):
                img_count += 1
            elif isinstance(c, Record):
                recs.append(c)
            elif isinstance(c, Video):
                vids.append(c)
        for _ in range(min(img_count, 3)):
            names.append("[对方发来一张图片或表情包]")
        if recs:
            txt = await self._transcribe_voice(event, recs[0])
            names.append(
                f"[对方发来一条语音，你清楚地听到他说：{txt}]" if txt
                else "[对方发来一条语音（你没听清）]"
            )
        if vids:
            desc = await asyncio.wait_for(self._process_video(event, vids[0]), timeout=150)
            names.append(f"[对方发来的视频，你看得很清楚：{desc}]")
        if names:
            extra = " ".join(names)
            if extra not in (event.message_str or ""):
                event.message_str = ((event.message_str or "") + " " + extra).strip()
                logger.info(f"[face_convert] 收信翻译: {extra}")

        # 身份标记（只进她的上下文，对方看不到字面量）：
        # 群聊 -> [昵称(QQ号)]，管理员标「主人」；陌生人私聊 -> [主人的朋友 昵称(QQ号)]
        try:
            if not event.get_extra("_fy_tagged"):
                sid = str(event.get_sender_id())
                is_group = bool(event.get_group_id())
                is_guest = (not is_group) and event.is_private_chat() and sid not in self.admins
                if is_group or is_guest:
                    name = re.sub(r"[\[\]\r\n]", "", (event.get_sender_name() or "").strip())[:16]
                    if is_group and sid in self.admins:
                        tag = f"主人({sid})"
                    elif is_group:
                        tag = f"{name}({sid})" if name else f"群友({sid})"
                    else:
                        tag = f"主人的朋友 {name}({sid})" if name else f"主人的朋友({sid})"
                    text = (event.message_str or "").strip()
                    if text:
                        event.message_str = f"[{tag}] {text}"
                        event.set_extra("_fy_tagged", True)
                        logger.info(f"[face_convert] 身份标记: {tag}")
                    elif is_group and event.is_wake and not any(
                        (isinstance(c, At) and str(c.qq) == str(event.get_self_id()))
                        or (
                            isinstance(c, Reply)
                            and str(getattr(c, "sender_id", "")) == str(event.get_self_id())
                        )
                        for c in comps
                    ):
                        # 只喊了名字、没带内容：给她一个回应的由头
                        event.message_str = f"[{tag}] （喊了你一声）"
                        event.set_extra("_fy_tagged", True)
                        logger.info(f"[face_convert] 群聊空唤醒标记: {tag}")
        except Exception as e:
            logger.warning(f"[face_convert] 身份标记失败: {str(e)[:100]}")

    SCRUB_RE = re.compile(r"[（(]{2}.*?[）)]{2}", re.DOTALL)
    # 嘴硬橡皮擦：擦掉"看不清/模模糊糊/隐约"类小尾巴（上下文回声病，人格治不动）
    # 边界字符集含半角标点/引号/空白，防咬边
    _HEDGE_STOP = r",\.。！？!?;；、：:~…“”\"（）()【】\[\]\s"
    HEDGE_RE = re.compile(
        f"[^{_HEDGE_STOP}]{{0,14}}"
        f"(?:看不太清|看不太清楚|看不清|模模糊糊|糊糊的|没看清也没听清|没听清|听不太清|听不清楚|听不清"
        f"|隐约(?:听见|听到|飘|看))"
        f"[^{_HEDGE_STOP}]{{0,14}}[，、：]?"
    )

    # meta 口癖关键字（引用了注入内容或自我说明的句子，整句丢）
    _META_BASE = (
        r"PROTOCOL_ENFORCEMENT|必须生成|必须输出|系统等待|系统自检|System:|星绘|报告前辈|"
        r"一个字都不理|不吃这套|又来又来|不照(?:着|谁)|钓鱼的饵|这饵"
    )
    META_KW = re.compile(_META_BASE)  # 私聊版：留着她"喊冤/自我修正"的通道
    # 群聊版：把"框框/顶着嘴"这类也擦掉——朋友们不该看到她拆自己的台
    META_KW_GROUP = re.compile(_META_BASE + r"|框框|顶着.{0,3}嘴")

    @filter.on_llm_response()
    async def scrub_drafts(self, event: AstrMessageEvent, response) -> None:
        """发送前的三道橡皮擦：①草稿箱（双层括号）②嘴硬小尾巴 ③meta 口癖句。"""
        try:
            text = getattr(response, "completion_text", None) or ""
            if not text:
                return
            cleaned = text
            if "（（" in cleaned or "((" in cleaned:
                cleaned = self.SCRUB_RE.sub("", cleaned)
                if cleaned != text:
                    logger.info("[face_convert] 已撕掉草稿箱内容")
            hedged = self.HEDGE_RE.sub("", cleaned)
            if hedged != cleaned:
                cleaned = hedged
                logger.info("[face_convert] 已擦掉嘴硬小尾巴")
            kw = self.META_KW_GROUP if event.get_group_id() else self.META_KW
            if kw.search(cleaned):
                # 按句丢弃带 meta 标记的句子（她那些"不理它/不照模板走"的前戏）
                parts = re.split(r"(?<=[。！？\n])", cleaned)
                kept = [s for s in parts if not kw.search(s)]
                joined = "".join(kept).replace("---", "")
                joined = re.sub(r"\n{2,}", "\n", joined).strip().strip("，、")
                # meta 句被整句丢掉以后可能留下配对不上的括号残骸（比如结尾一个
                # 孤零零的"）"）。按数量补删：哪种括号多出来就删哪个，配对好的不动。
                for op, cl in (("（", "）"), ("(", ")"), ("【", "】"), ("《", "》")):
                    while joined.count(cl) > joined.count(op):
                        joined = joined[::-1].replace(cl, "", 1)[::-1]
                    while joined.count(op) > joined.count(cl):
                        joined = joined[::-1].replace(op, "", 1)[::-1]
                joined = joined.strip()
                if joined.strip("，。！？、：;；~… \n"):
                    cleaned = joined
                    logger.info("[face_convert] 已清扫 meta 口癖")
                else:
                    # 整条都是口癖 -> 鱼的沉默
                    cleaned = "……"
                    logger.info("[face_convert] 全条 meta，已压成沉默")
            cleaned = cleaned.strip()
            if not cleaned.strip("，。！？、：;；~… \n"):
                # 整条都被擦光 -> 换成鱼的沉默
                cleaned = "……"
            if cleaned != text:
                response.completion_text = cleaned
        except Exception as e:
            logger.warning(f"[face_convert] 草稿清理失败: {e}")

    @filter.on_decorating_result()
    async def convert_faces(self, event: AstrMessageEvent):
        result = event.get_result()
        if result is None or not result.is_llm_result():
            return

        # 思维链防漏：EmotionAI 的 <thought> 块偶尔会漏进消息（甚至被 TTS 念出来）。
        # 在"出门关口"再查一遍，不影响 EmotionAI 自己的情绪提取。
        if any(
            isinstance(c, Plain) and c.text and "<thought" in c.text
            for c in result.chain
        ):
            cleaned_chain = []
            for c in result.chain:
                if isinstance(c, Plain) and c.text:
                    t = re.sub(r"<thought>.*?</thought>", "", c.text, flags=re.DOTALL)
                    # 未闭合的 <thought>：从它一直截到结尾
                    t = re.sub(r"<thought>.*$", "", t, flags=re.DOTALL)
                    t = t.replace("</thought>", "").strip()
                    if not t:
                        continue
                    c.text = t
                cleaned_chain.append(c)
            logger.info("[face_convert] 已摘掉漏出的 <thought> 思维链块")
            if not cleaned_chain:
                result.chain = []
                return
            result.chain = cleaned_chain

        # 暗号：整条消息都是怪东西时，LLM 只输出 [NO_REPLY] -> 整条回复蒸发
        joined = "".join(
            c.text for c in result.chain if isinstance(c, Plain) and c.text
        )
        if "[NO_REPLY]" in joined.upper():
            result.chain = []
            logger.info("[face_convert] 收到 [NO_REPLY] 暗号，已吞掉这条回复")
            return

        new_chain = []
        changed = 0
        stripped = 0
        dropped_faces = 0
        per_msg = 0
        for comp in result.chain:
            if not isinstance(comp, Plain) or not comp.text:
                new_chain.append(comp)
                continue
            text = comp.text
            pos = 0
            for m in self.pattern.finditer(text):
                if changed >= MAX_REPLACE:
                    break
                name = m.group(1).strip()
                fid = self.face_map.get(name)
                if fid is None:
                    # 兜底：像表情名的短词（1~6个中文/字母）但字典不认 ->
                    # 去掉方括号保留文字，起码不是一堆 [ ] 裸奔
                    if re.fullmatch(r"[A-Za-z一-鿿]{1,6}", name):
                        if m.start() > pos:
                            new_chain.append(Plain(text[pos : m.start()]))
                        new_chain.append(Plain(name))
                        pos = m.end()
                        stripped += 1
                    continue
                # 表情冷却：同一张脸最近 2 次用过就消失；每条最多 2 张
                if per_msg >= 2 or fid in self._recent_faces[-2:]:
                    if m.start() > pos:
                        new_chain.append(Plain(text[pos : m.start()]))
                    pos = m.end()
                    dropped_faces += 1
                    continue
                if m.start() > pos:
                    new_chain.append(Plain(text[pos : m.start()]))
                new_chain.append(Face(id=fid))
                self._recent_faces.append(fid)
                self._recent_faces = self._recent_faces[-8:]
                per_msg += 1
                pos = m.end()
                changed += 1
            if pos < len(text):
                new_chain.append(Plain(text[pos:]))

        if changed or stripped or dropped_faces:
            result.chain = new_chain
            logger.info(
                f"[face_convert] 已转换 {changed} 个文字表情 -> 真实表情段"
                + (f"，脱括号 {stripped} 个（字典不认的）" if stripped else "")
                + (f"，冷却丢弃 {dropped_faces} 个" if dropped_faces else "")
            )

    # ---------------- 语音开关（会话级，走 AstrBot 官方会话配置） ----------------

    @filter.command("语音开")
    async def voice_on(self, event: AstrMessageEvent):
        """开启本会话的语音条。"""
        await SessionServiceManager.set_tts_status_for_session(
            event.unified_msg_origin, True
        )
        yield event.plain_result("开麦！想听我说话就多喊我两句呀~")

    @filter.command("语音关")
    async def voice_off(self, event: AstrMessageEvent):
        """关闭本会话的语音条（文字照常聊）。"""
        await SessionServiceManager.set_tts_status_for_session(
            event.unified_msg_origin, False
        )
        yield event.plain_result("好嘛好嘛，我先闭嘴，文字照聊！（小声嘟囔）")

    @filter.command("语音状态")
    async def voice_status(self, event: AstrMessageEvent):
        """查询本会话的语音条开关状态。"""
        on = await SessionServiceManager.is_tts_enabled_for_session(
            event.unified_msg_origin
        )
        yield event.plain_result(f"语音条现在是{'开' if on else '关'}的哦~")
