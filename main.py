import asyncio
import base64
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

ASTRBOT_ADMIN_CONFIG_KEYS = {
    "admins",
    "admin_ids",
    "admins_id",
    "admin_users",
    "admin_user_ids",
    "admin_qq",
    "admin_qqs",
    "administrator_ids",
    "administrators",
    "superusers",
    "super_users",
}


@dataclass
class ImageRequest:
    prompt: str
    aspect_ratio: str
    model: str
    reference_images: list[str]


@register(
    "astrbot_plugin_grsai_image",
    "Codex",
    "Use GRSAI gpt-image-2 to generate images.",
    "0.2.0",
)
class GrsaiImagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._last_used: dict[str, float] = {}
        self._quota_file = Path("/AstrBot/data/plugin_data/grsai_image/quota_usage.json")
        self._astrbot_config_file = Path("/AstrBot/data/cmd_config.json")
        self._quota_usage = self._load_quota_usage()

    @filter.command("画图", alias={"生图", "生成图片"})
    async def generate_image(self, event: AstrMessageEvent):
        """使用 GRSAI 生成图片。示例：/画图 --ratio 16:9 --4k 赛博朋克城市夜景"""
        sender_id = str(event.get_sender_id())
        policy_error = self._check_usage_policy(sender_id)
        if policy_error:
            yield event.plain_result(policy_error)
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
            reference_images = await self._collect_reference_images(event)
            image_req = self._parse_message(event.message_str, reference_images)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return

        self._last_used[sender_id] = time.monotonic()
        ref_text = f"，参考图 {len(image_req.reference_images)} 张" if image_req.reference_images else ""
        yield event.plain_result(f"已收到，正在生成图片：{image_req.aspect_ratio}{ref_text}")

        try:
            image_url = await self._call_grsai(image_req, api_key)
        except Exception as exc:
            logger.error(f"GRSAI image generation failed: {exc}")
            yield event.plain_result(f"生成失败：{exc}")
            return

        self._record_quota_usage(sender_id)
        yield event.image_result(image_url)

    @filter.command("image_help", alias={"图片帮助", "画图帮助", "生图帮助"})
    async def image_help(self, event: AstrMessageEvent):
        """Show image command usage, aspect ratios, and resolution examples."""
        yield event.plain_result(
            "\n".join(
                [
                    "GRSAI 画图帮助",
                    "",
                    "基础用法：",
                    "/画图 提示词",
                    "/生图 提示词",
                    "",
                    "设置长宽比：",
                    "/画图 --ratio 16:9 提示词",
                    "/画图 --ratio 9:16 提示词",
                    "/画图 --ratio 1:1 提示词",
                    "",
                    "生成 4K：",
                    "/画图 --4k --ratio 16:9 提示词",
                    "16:9 4K = 3840x2160",
                    "9:16 4K = 2160x3840",
                    "1:1 4K = 2880x2880",
                    "",
                    "直接指定分辨率：",
                    "/画图 --size 3840x2160 提示词",
                    "/画图 --size 2048x2048 提示词",
                    "",
                    "图生图：",
                    "引用一张图片，然后发 /画图 提示词",
                    "或在同一条消息里带图并写 /画图 提示词",
                    "",
                    "常用 2K：",
                    "1:1 = 2048x2048",
                    "16:9 = 2048x1152",
                    "9:16 = 1152x2048",
                    "3:2 = 2048x1360",
                    "2:3 = 1360x2048",
                    "",
                    "常用 4K：",
                    "16:9 = 3840x2160",
                    "9:16 = 2160x3840",
                    "3:2 = 3504x2336",
                    "2:3 = 2336x3504",
                    "2:1 = 3840x1920",
                    "1:2 = 1920x3840",
                    "",
                    "示例：",
                    "/画图 --4k --ratio 16:9 雨夜赛博朋克城市，电影感，超清细节",
                ]
            )
        )

    def _check_usage_policy(self, sender_id: str) -> str | None:
        if sender_id in self._string_list("blacklist_user_ids"):
            return str(self.config.get("blacklist_reply", "你已被加入画图黑名单，无法使用该功能。"))

        if self._is_quota_exempt(sender_id):
            return None

        restricted_ids = self._string_list("restricted_user_ids")
        if restricted_ids and sender_id not in restricted_ids:
            return str(self.config.get("not_allowed_reply", "你暂时没有使用画图功能的权限。"))

        disabled_reason = self._disabled_time_reason()
        if disabled_reason:
            return disabled_reason

        daily_limit = int(self.config.get("daily_quota_limit", 3))
        if daily_limit > 0 and self._quota_used_today(sender_id) >= daily_limit:
            return str(
                self.config.get(
                    "quota_exceeded_reply",
                    f"你今天的画图额度已用完（{daily_limit} 张/天），明天再来吧。",
                )
            )
        return None

    def _disabled_time_reason(self) -> str | None:
        if not bool(self.config.get("time_limit_enabled", True)):
            return None
        start = str(self.config.get("disabled_start_time", "00:00"))
        end = str(self.config.get("disabled_end_time", "08:00"))
        start_time = self._parse_hhmm(start)
        end_time = self._parse_hhmm(end)
        if not start_time or not end_time:
            return None

        now = datetime.now(self._local_timezone()).time()
        if start_time <= end_time:
            disabled = start_time <= now < end_time
        else:
            disabled = now >= start_time or now < end_time
        if not disabled:
            return None
        return str(self.config.get("time_limit_reply", f"画图功能在 {start}-{end} 暂停使用，请稍后再试。"))

    def _parse_hhmm(self, value: str):
        try:
            return datetime.strptime(value.strip(), "%H:%M").time()
        except ValueError:
            logger.warning(f"Invalid time config: {value}")
            return None

    def _quota_key(self) -> str:
        return datetime.now(self._local_timezone()).strftime("%Y-%m-%d")

    def _local_timezone(self) -> ZoneInfo:
        timezone_name = str(self.config.get("timezone", "Asia/Shanghai")).strip() or "Asia/Shanghai"
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning(f"Invalid timezone config: {timezone_name}, fallback to Asia/Shanghai")
            return ZoneInfo("Asia/Shanghai")

    def _quota_used_today(self, sender_id: str) -> int:
        return int(self._quota_usage.get(self._quota_key(), {}).get(sender_id, 0))

    def _record_quota_usage(self, sender_id: str):
        if self._is_quota_exempt(sender_id):
            return
        day = self._quota_key()
        self._quota_usage.setdefault(day, {})
        self._quota_usage[day][sender_id] = int(self._quota_usage[day].get(sender_id, 0)) + 1
        for key in list(self._quota_usage.keys()):
            if key != day:
                self._quota_usage.pop(key, None)
        self._save_quota_usage()

    def _load_quota_usage(self) -> dict:
        try:
            if self._quota_file.exists():
                with open(self._quota_file, "r", encoding="utf-8") as file:
                    data = json.load(file)
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning(f"Failed to load GRSAI quota usage: {exc}")
        return {}

    def _save_quota_usage(self):
        try:
            self._quota_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._quota_file, "w", encoding="utf-8") as file:
                json.dump(self._quota_usage, file, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"Failed to save GRSAI quota usage: {exc}")

    def _string_list(self, key: str) -> list[str]:
        return [str(item).strip() for item in self.config.get(key, []) if str(item).strip()]

    def _is_quota_exempt(self, sender_id: str) -> bool:
        return sender_id in self._string_list("allowed_user_ids") or sender_id in self._astrbot_admin_ids()

    def _astrbot_admin_ids(self) -> set[str]:
        try:
            with open(self._astrbot_config_file, "r", encoding="utf-8-sig") as file:
                data = json.load(file)
        except FileNotFoundError:
            return set()
        except Exception as exc:
            logger.warning(f"Failed to read AstrBot admin config: {exc}")
            return set()

        admin_ids: set[str] = set()

        def add_value(value):
            if isinstance(value, bool):
                return
            if isinstance(value, (str, int)):
                text = str(value).strip()
                if text:
                    admin_ids.add(text)
                return
            if isinstance(value, list):
                for item in value:
                    add_value(item)
                return
            if isinstance(value, dict):
                for item_key in ("id", "qq", "user_id", "uin"):
                    if item_key in value:
                        add_value(value[item_key])

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    normalized_key = str(key).strip().lower().replace("-", "_")
                    if normalized_key in ASTRBOT_ADMIN_CONFIG_KEYS:
                        add_value(item)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(data)
        return admin_ids

    def _get_cooldown_left(self, sender_id: str) -> int:
        cooldown = int(self.config.get("cooldown_seconds", 60))
        if cooldown <= 0:
            return 0
        last_used = self._last_used.get(sender_id, 0)
        elapsed = time.monotonic() - last_used
        return max(0, int(cooldown - elapsed))

    def _parse_message(self, message: str, reference_images: list[str]) -> ImageRequest:
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

        return ImageRequest(
            prompt=text,
            aspect_ratio=aspect_ratio,
            model=model,
            reference_images=reference_images,
        )

    async def _collect_reference_images(self, event: AstrMessageEvent) -> list[str]:
        max_images = int(self.config.get("max_reference_images", 1))
        if max_images <= 0:
            return []

        sources = self._image_sources_from_components(getattr(event.message_obj, "message", []) or [])
        if not sources:
            reply_id = self._extract_reply_message_id(event)
            if reply_id:
                sources = await self._image_sources_from_reply(event, reply_id)

        images = []
        for source in sources[:max_images]:
            try:
                images.append(await self._source_to_data_url(source))
            except Exception as exc:
                logger.warning(f"Failed to load reference image {source}: {exc}")
        return images

    async def _image_sources_from_reply(self, event: AstrMessageEvent, message_id: str) -> list[str]:
        bot = getattr(event, "bot", None)
        api = getattr(bot, "api", None)
        if not api:
            return []
        try:
            ret = await api.call_action("get_msg", message_id=int(message_id))
        except Exception as exc:
            logger.warning(f"Failed to fetch replied message {message_id}: {exc}")
            return []
        message = ret.get("message") if isinstance(ret, dict) else getattr(ret, "message", None)
        return self._image_sources_from_raw_message(message)

    def _image_sources_from_components(self, components) -> list[str]:
        sources = []
        for component in components:
            type_value = str(getattr(getattr(component, "type", ""), "value", getattr(component, "type", ""))).lower()
            class_name = component.__class__.__name__.lower()
            if "image" not in type_value and "image" not in class_name:
                continue
            for attr in ("url", "file", "file_", "path"):
                value = getattr(component, attr, None)
                if value:
                    sources.append(str(value))
                    break
        return sources

    def _image_sources_from_raw_message(self, message) -> list[str]:
        sources = []
        if not message:
            return sources
        for segment in list(message):
            if isinstance(segment, dict):
                seg_type = str(segment.get("type", "")).lower()
                data = segment.get("data") or {}
                if seg_type == "image":
                    source = data.get("url") or data.get("file") or data.get("path")
                    if source:
                        sources.append(str(source))
            else:
                sources.extend(self._image_sources_from_components([segment]))
        return sources

    def _extract_reply_message_id(self, event: AstrMessageEvent) -> str | None:
        for component in getattr(event.message_obj, "message", []) or []:
            type_value = str(getattr(getattr(component, "type", ""), "value", getattr(component, "type", ""))).lower()
            class_name = component.__class__.__name__.lower()
            if "reply" in type_value or "reply" in class_name:
                for attr in ("id", "message_id"):
                    value = getattr(component, attr, None)
                    if value:
                        return str(value)

        raw = getattr(event.message_obj, "raw_message", None)
        raw_message = raw.get("message") if isinstance(raw, dict) else getattr(raw, "message", None)
        if raw_message:
            for segment in list(raw_message):
                if isinstance(segment, dict) and str(segment.get("type", "")).lower() == "reply":
                    data = segment.get("data") or {}
                    value = data.get("id") or data.get("message_id")
                    if value:
                        return str(value)
        return None

    async def _source_to_data_url(self, source: str) -> str:
        if source.startswith("data:image/"):
            return source
        if source.startswith("file://"):
            source = source[7:]
        if source.startswith("http://") or source.startswith("https://"):
            timeout = int(self.config.get("timeout_seconds", 600))
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(source)
                response.raise_for_status()
                content = response.content
                mime = response.headers.get("content-type", "").split(";")[0] or self._guess_mime(source)
        else:
            if not os.path.exists(source):
                raise FileNotFoundError(source)
            with open(source, "rb") as file:
                content = file.read()
            mime = self._guess_mime(source)
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _guess_mime(self, source: str) -> str:
        mime, _ = mimetypes.guess_type(source)
        return mime or "image/png"

    async def _call_grsai(self, image_req: ImageRequest, api_key: str) -> str:
        base_url = str(self.config.get("base_url", "https://grsai.dakka.com.cn")).strip().rstrip("/")
        timeout = int(self.config.get("timeout_seconds", 600))
        url = f"{base_url}/v1/api/generate"
        headers = {
            "Authorization": f"Bearer {api_key.removeprefix('Bearer ').strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AstrBot-GRSAI-Image/0.2",
        }
        reply_type = str(self.config.get("reply_type", "async")).strip() or "async"
        payload = {
            "model": image_req.model,
            "prompt": image_req.prompt,
            "aspectRatio": image_req.aspect_ratio,
            "replyType": reply_type,
        }
        if image_req.reference_images:
            payload["images"] = image_req.reference_images
        quality = str(self.config.get("gpt_quality", "high")).strip()
        if quality and quality != "auto":
            payload["quality"] = quality

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await self._request_with_retries(
                client,
                "POST",
                url,
                retry_label="generate",
                headers=headers,
                json=payload,
            )
            data = self._parse_response(response)

            if reply_type == "async" or data.get("status") == "running":
                task_id = data.get("id")
                if not task_id:
                    raise RuntimeError(f"异步任务没有返回 id: {data}")
                data = await self._poll_result(client, base_url, headers, task_id)

        return self._extract_image_url(data)

    async def _poll_result(
        self, client: httpx.AsyncClient, base_url: str, headers: dict[str, str], task_id: str
    ) -> dict:
        result_url = f"{base_url}/v1/api/result"
        interval = max(1, int(self.config.get("poll_interval_seconds", 10)))
        max_wait = max(interval, int(self.config.get("max_poll_seconds", 600)))
        deadline = time.monotonic() + max_wait

        last_data = None
        last_error = None
        while time.monotonic() <= deadline:
            try:
                response = await self._request_with_retries(
                    client,
                    "GET",
                    result_url,
                    retry_label="result",
                    headers=headers,
                    params={"id": task_id},
                    max_retry_seconds=interval,
                )
                data = self._parse_response(response)
                last_error = None
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(f"GRSAI result polling transient error: {exc}")
                await asyncio.sleep(interval)
                continue
            last_data = data
            status = data.get("status")
            if status in {"succeeded", "failed", "violation"}:
                return data
            await asyncio.sleep(interval)

        progress = ""
        if isinstance(last_data, dict) and last_data.get("progress") is not None:
            progress = f"，最后进度 {last_data.get('progress')}%"
        if last_error:
            progress = f"{progress}，最后错误：{last_error}"
        raise RuntimeError(f"生成超时，任务 id={task_id}{progress}")

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        retry_label: str,
        max_retry_seconds: int | None = None,
        **kwargs,
    ) -> httpx.Response:
        interval = max(1, int(self.config.get("poll_interval_seconds", 10)))
        max_retry_seconds = max_retry_seconds or int(self.config.get("request_retry_seconds", 120))
        deadline = time.monotonic() + max_retry_seconds

        while True:
            try:
                return await client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if time.monotonic() >= deadline:
                    raise
                logger.warning(f"GRSAI {retry_label} transient error, retrying: {exc}")
                await asyncio.sleep(interval)

    def _parse_response(self, response: httpx.Response) -> dict:
        body_preview = response.text[:500].strip()
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"HTTP {response.status_code}: {body_preview or exc.response.reason_phrase}") from exc
        try:
            return response.json()
        except JSONDecodeError as exc:
            content_type = response.headers.get("content-type", "unknown")
            raise RuntimeError(
                f"接口没有返回 JSON。content-type={content_type}, body={body_preview or '<empty>'}"
            ) from exc

    def _extract_image_url(self, data: dict) -> str:
        status = data.get("status")
        if status == "violation":
            raise RuntimeError(data.get("error") or "内容可能违规，服务拒绝生成。")
        if status == "failed":
            raise RuntimeError(data.get("error") or "任务失败。")
        if status != "succeeded":
            progress = data.get("progress")
            suffix = f"，当前进度 {progress}%" if progress is not None else ""
            raise RuntimeError(f"任务状态为 {status}{suffix}。")

        results = data.get("results") or []
        if not results or not results[0].get("url"):
            raise RuntimeError("接口返回成功，但没有图片 URL。")
        return results[0]["url"]

    async def terminate(self):
        pass
