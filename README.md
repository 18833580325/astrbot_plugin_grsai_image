# GRSAI Image for AstrBot

AstrBot 的 GRSAI `gpt-image-2` / `gpt-image-2-vip` 画图插件。

## 命令

```text
/画图 一只边牧在直播间带货
/生图 --ratio 16:9 赛博朋克城市夜景
/画图 --4k --ratio 9:16 白发少女，星空背景
/画图 --size 2048x2048 水彩风格的小镇
```

图生图：引用一张图片，然后发送 `/画图 提示词`。

## 常用配置

- `api_key`: GRSAI API Key，不需要 `Bearer`。
- `base_url`: `https://grsai.dakka.com.cn` 或 `https://grsaiapi.com`。
- `model`: 推荐 `gpt-image-2-vip`，支持 2K/4K。
- `cooldown_seconds`: 单用户冷却时间。
- `active_generation_reply`: 同一个用户上一条画图任务没结束时的回复。
- `allowed_user_ids`: 白名单，不受额度和禁用时段限制。
- `restricted_user_ids`: 留空表示所有非黑名单用户可用；不为空时，只允许白名单和此列表用户使用。
- `blacklist_user_ids`: 黑名单，不能使用画图功能。

## 色情视觉审核

开启 `vision_review_enabled` 后，插件会在 GRSAI 生成成功后、发送图片前调用 AstrBot 的视觉模型审核。

审核只判断图片是否包含色情或性内容，不审查图片里的文字、水印、签名、标语、logo、政治文字或其他文本内容。

相关配置：

- `vision_review_enabled`: 是否启用生成后色情审核。
- `vision_review_mode`: `astrbot_caption`、`astrbot_current` 或 `off`。
- `review_exempt_user_ids`: 免审查用户 QQ 号；只跳过视觉审核，不影响黑名单。
- `vision_review_fail_closed`: 审核模型报错时是否禁止发送。
- `vision_block_reply`: 审核拦截时发给用户的简短回复。
- `vision_review_prompt`: 审核提示词，要求模型只返回 JSON。

如果使用 `astrbot_caption`，请先在 AstrBot 中配置图片描述模型。

## 安装

复制本文件夹到：

```text
/opt/astrbot/astrbot/data/plugins/astrbot_plugin_grsai_image
```

然后重启 AstrBot 或在 WebUI 里重载插件。
