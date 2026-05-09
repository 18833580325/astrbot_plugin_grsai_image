# GRSAI Image for AstrBot

Use GRSAI `gpt-image-2` / `gpt-image-2-vip` to generate images from QQ commands.

## Commands

```text
/画图 一只边牧在直播间带货
/生图 --ratio 16:9 赛博朋克城市夜景
/画图 --4k --ratio 9:16 白发少女，星空背景
/画图 --size 2048x2048 水彩风格的小镇
```

## Config

Configure the plugin in AstrBot WebUI:

- `api_key`: GRSAI API Key, without `Bearer`.
- `base_url`: `https://grsai.dakka.com.cn` or `https://grsaiapi.com`.
- `model`: `gpt-image-2-vip` is recommended for 2K/4K.
- `cooldown_seconds`: per-user cooldown.
- `allowed_user_ids`: empty means everyone can use it.

## Install

Copy this folder to:

```text
/opt/astrbot/astrbot/data/plugins/astrbot_plugin_grsai_image
```

Then restart AstrBot or reload the plugin from WebUI.
