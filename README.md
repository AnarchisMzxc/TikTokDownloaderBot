# TikTokDownloaderBot
*[Russian version](README_ru.md)*

A Telegram bot that grabs videos/audio from YouTube, TikTok, Instagram and Pinterest and hands them back to you as a file — either by just pasting a link in chat, or through inline mode (`@yourbot <link>` in literally any chat).

Built with `aiogram 3`, `yt-dlp`, and `ffmpeg` for the trimming.

## What it actually does

- Paste a link → bot replies with buttons: **Video / Audio (MP3) / 30-sec clip**. Tap one, it downloads and sends the file. No auto-downloading on every link someone posts — it just offers, you decide.
- Same thing works inline: type `@yourbot <link>` in any chat (even ones the bot isn't in) and you get the same three options as inline query results.
- Downloads are queued through a worker pool (`asyncio.Queue` + a fixed number of workers), so five people spamming links at once doesn't fork five `yt-dlp`/`ffmpeg` processes and choke the box.
- TikTok gets special treatment: instead of fighting yt-dlp's anti-bot challenge on every request, it tries [tikwm.com](https://tikwm.com)'s API first (plain HTTP call, no captcha drama) and only falls back to yt-dlp if that's down.
- There's a hidden `/debug <link>` command (admin-only) that runs yt-dlp in verbose mode and sends you the log as a file — handy when you're on a host where "console" just means bot stdout and you can't run `yt-dlp -vU` by hand.

## Before you run it

You need:
- Python 3.11+
- `ffmpeg` installed on the system (not the pip package — the actual binary). `apt install ffmpeg` on Debian/Ubuntu, `brew install ffmpeg` on Mac.
- A bot token from [@BotFather](https://t.me/BotFather).

```bash
python -m venv venv
source venv/bin/activate   # venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Then:

```bash
cp .env.example .env
```

Open `.env` and fill in `BOT_TOKEN` at minimum. Everything else has a sane default, see the comments in `.env.example`.

Run it:

```bash
python main.py
```

## Setting up inline mode (this part's a bit fiddly)

Inline mode needs two things flipped on in BotFather that aren't on by default:

1. **Inline mode itself** — should already be on if BotFather gave you an inline placeholder when you made the bot. If not: `/setinline`.
2. **Inline feedback** — `/setinlinefeedback` → pick your bot → **100%**. Without this, Telegram never tells your bot which option someone tapped (the `chosen_inline_result` event just never arrives), and the "⏳ downloading..." placeholder sits there forever looking broken. This one trips people up a lot.

There's also a Telegram API quirk worth knowing about: when you edit an inline message to swap the placeholder for the actual video, Telegram **won't let you upload a fresh local file** for that edit — only a file that already has a `file_id` (i.e. something you already sent through the bot once) or a direct URL. So the bot's workaround is: download the file, quietly send it to a chat it controls first (`STORAGE_CHAT_ID`, falls back to `ADMIN_ID` if you don't set one separately) to get a `file_id` back, delete that copy, *then* use the file_id to edit the inline message. Net effect: whichever chat you set as the storage chat will briefly see a copy of everything anyone downloads via inline mode. That's expected, not a bug — just pick a chat you're okay with that (your own DM with the bot is the easy default).

## Env vars, all of them

| Var | What it does |
|---|---|
| `BOT_TOKEN` | from BotFather, required |
| `MAX_WORKERS` | how many downloads run in parallel |
| `QUEUE_MAX_SIZE` | how many can be queued before people get a "try later" |
| `MAX_VIDEO_HEIGHT` | caps download quality, e.g. 1080 |
| `DOWNLOAD_DIR` | scratch folder for downloads, cleaned up after each send |
| `ADMIN_ID` | your numeric Telegram id, unlocks `/debug` and doubles as the default storage chat |
| `STORAGE_CHAT_ID` | override for the inline file_id trick above, if you want it separate from ADMIN_ID |
| `TIKTOK_BACKEND` | `auto` (tikwm → yt-dlp fallback), `tikwm`, or `ytdlp` |
| `COOKIES_FILE` | path to a `cookies.txt` (Netscape format) — sometimes needed if a source site starts captcha-walling your host's IP |
| `PROXY_URL` | proxy for yt-dlp requests, e.g. if your hosting IP gets blocked outright |

Get your numeric Telegram id from [@userinfobot](https://t.me/userinfobot) if you need it.

## The Telegram 50MB thing

Regular bots (not self-hosted Bot API servers) can't send files bigger than 50MB. If a video's too chunky, the bot tells you instead of just failing silently. If you need bigger files regularly, you're looking at running your own [Bot API server](https://github.com/tdlib/telegram-bot-api).

## TikTok breaking randomly? That's normal

TikTok changes its site/API often enough that yt-dlp's TikTok extractor breaks every few weeks, gets patched, breaks again. If TikTok links stop working:

1. Update yt-dlp: `pip install -U yt-dlp`. If that doesn't fix it, try the nightly build, fixes usually land there first: `pip install -U --pre yt-dlp`.
2. This bot tries tikwm.com first anyway (see `TIKTOK_BACKEND`), which sidesteps most of this — it's a separate service that's already resolved the video on its end, so yt-dlp's TikTok extractor being broken doesn't matter until tikwm is *also* down.
3. Use `/debug <link>` to get a proper error log without needing shell access to the host.

Don't bother hardcoding TikTok-specific workarounds (custom API hostnames, etc.) into the extractor options — they go stale faster than they help and you end up debugging your own patch instead of the actual problem.

## A note on legality

This bot downloads content from platforms whose ToS generally don't love that (YouTube, Instagram, TikTok, Pinterest). yt-dlp and tikwm are legal tools/services in themselves, but what you do with what they fetch — personal archive vs. redistributing other people's videos to a wide audience — is on you. Use it responsibly.

## Project layout

```
main.py              # entrypoint, wires everything up
config.py             # env vars live here
queue_manager.py       # bounded async queue + worker pool
downloader.py           # yt-dlp / tikwm / ffmpeg, all the actual download logic
pending.py               # short-id store for callback_data / inline result ids (both have a 64-byte cap)
handlers/
  direct.py               # regular chat: link → buttons → download
  inline.py                # inline mode: query → options → chosen_inline_result → download
```
Lucky!
