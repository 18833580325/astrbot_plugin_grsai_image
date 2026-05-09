import re
import time
from dataclasses import dataclass

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


SIZE_TABLE = {
    "1k": {
        "1:1": "1024x1024",
        "16:9": "1774x887",
        "9:16": "887x1774",
        "3:2": "1536x1024",
        "2:3": "1024x1536",
    },
    "2k": {
        "1:1": "2048x2048",
        "16:9": "2048x1152",
        "9:16": "1152x2048",
        "3:2": "2048x1360",
        "2:3": "1360x2048",
        "21:9": "2048x880",
        "9:21": "880x2048",
        "1:3": "688x2048",
        "3:1": "2048x688",
        "2:1": "2048x1024",
        "1:2": "1024x2048",
    },
    "4k": {
        "1:1": "2880x2880",
        "16:9": "3840x2160",
        "9:16": "2160x3840",
        "3:2": "3504x2336",
        "2:3": "2336x3504",
        "21:9": "3840x1648",
        "9:21": "1648x3840",
        "1:3": "1280x3840",
        "3:1": "3840x1280",
        "2:1": "3840x1920",
        "1:2": "1920x3840",
    },
}


@dataclass
class ImageRequest:
    prompt: str
    aspect_ratio: str
    model: str


@register(
    "astrbot_plugin_grsai_image",
    "Codex",
    "Use GRSAI gpt-image-2 to generate images.",
    "0.1.0",
)
class GrsaiImagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._last_used: dict[str, float] = {}

    @filter.command("画图", alias={"生图", "生成图片"})
    async def generate_image(self, event: AstrMessageEvent):
        """使用 GRSAI 生成图片。示例：/画图 --ratio 16:9 --4k 赛博朋克城市夜景"""
        sender_id = str(event.get_sender_id())
        allowed_ids = [str(item) for item in self.config.get("allowed_user_ids", [])]
        if allowed_ids and sender_id not in allowed_ids:
            yield event.plain_result("你暂时没有使用画图功能的权限。")
            return

        api_key = str(self.config.get("api_key", "")).strip()
        if not api_key:
            yield event.plain_result("GRSAI API Key 还没配置，请先在插件配置里填写 api_key。")
            return

        cooldown_left = self._get_cooldown_left(sender_id)
        if cooldown_left > 0:
            yield event.plain_result(f"画图冷却中，还需要等待 {cooldown_left} 秒。")
            return

        try:
            image_req = self._parse_message(event.message_str)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return

        self._last_used[sender_id] = time.monotonic()
        yield event.plain_result(f"已收到，正在生成图片：{image_req.aspect_ratio}")

        try:
            image_url = await self._call_grsai(image_req, api_key)
        except Exception as exc:
            logger.error(f"GRSAI image generation failed: {exc}")
            yield event.plain_result(f"生成失败：{exc}")
            return

        yield event.image_result(image_url)

    def _get_cooldown_left(self, sender_id: str) -> int:
        cooldown = int(self.config.get("cooldown_seconds", 60))
        if cooldown <= 0:
            return 0
        last_used = self._last_used.get(sender_id, 0)
        elapsed = time.monotonic() - last_used
        return max(0, int(cooldown - elapsed))

    def _parse_message(self, message: str) -> ImageRequest:
        text = re.sub(r"^[/／]?(画图|生图|生成图片)\s*", "", message).strip()
        if not text:
            raise ValueError("请在命令后面写提示词，例如：/画图 一只边牧在直播间带货")

        model = str(self.config.get("model", "gpt-image-2-vip")).strip() or "gpt-image-2-vip"
        quality = str(self.config.get("default_quality", "2k")).lower()
        ratio = str(self.config.get("default_ratio", "1:1")).strip() or "1:1"
        explicit_size = None

        if re.search(r"(^|\s)--4k(\s|$)|(^|\s)4k(图|图片)?(\s|$)", text, re.I):
            quality = "4k"
            text = re.sub(r"(^|\s)--4k(\s|$)|(^|\s)4k(图|图片)?(\s|$)", " ", text, flags=re.I).strip()

        ratio_match = re.search(r"--ratio\s+([0-9]+:[0-9]+)", text, re.I)
        if ratio_match:
            ratio = ratio_match.group(1)
            text = re.sub(r"--ratio\s+[0-9]+:[0-9]+", " ", text, flags=re.I).strip()

        size_match = re.search(r"--size\s+([0-9]{3,4}x[0-9]{3,4})", text, re.I)
        if size_match:
            explicit_size = size_match.group(1).lower()
            text = re.sub(r"--size\s+[0-9]{3,4}x[0-9]{3,4}", " ", text, flags=re.I).strip()

        if not text:
            raise ValueError("提示词为空，请补充要生成的画面内容。")

        aspect_ratio = explicit_size or SIZE_TABLE.get(quality, {}).get(ratio)
        if not aspect_ratio:
            supported = "、".join(SIZE_TABLE.get(quality, SIZE_TABLE["2k"]).keys())
            raise ValueError(f"不支持 {quality} 的比例 {ratio}，可用比例：{supported}")

        return ImageRequest(prompt=text, aspect_ratio=aspect_ratio, model=model)

    async def _call_grsai(self, image_req: ImageRequest, api_key: str) -> str:
        base_url = str(self.config.get("base_url", "https://grsai.dakka.com.cn")).strip().rstrip("/")
        timeout = int(self.config.get("timeout_seconds", 180))
        url = f"{base_url}/v1/api/generate"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": image_req.model,
            "prompt": image_req.prompt,
            "images": [],
            "aspectRatio": image_req.aspect_ratio,
            "replyType": "json",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        status = data.get("status")
        if status == "violation":
            raise RuntimeError(data.get("error") or "内容可能违规，服务拒绝生成。")
        if status == "failed":
            raise RuntimeError(data.get("error") or "任务失败。")
        if status != "succeeded":
            progress = data.get("progress")
            suffix = f"，当前进度 {progress}%" if progress is not None else ""
            raise RuntimeError(f"任务状态为 {status}{suffix}，当前版本插件使用 json 同步返回。")

        results = data.get("results") or []
        if not results or not results[0].get("url"):
            raise RuntimeError("接口返回成功，但没有图片 URL。")

        return results[0]["url"]

    async def terminate(self):
        pass
