<div align="center">

<img src="docs/CBML-banner.jpg" alt="CBML Banner" width="100%"/>

<br/>

# ⚡ CBML ⚡
### *CantarellaBots Mirror & Leech — Ultra-Fast Telegram & Cloud Engine*

[![GitHub Repository](https://img.shields.io/badge/GitHub-abhinai2244%2FCBML-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/abhinai2244/CBML)
[![Telegram Channel](https://img.shields.io/badge/Telegram-@CantarellaBots-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://t.me/cantarellabots)
[![Developer](https://img.shields.io/badge/Developer-@cantarella__wuwa-EA4335?style=flat-square&logo=telegram&logoColor=white)](https://t.me/cantarella_wuwa)
[![Python Version](https://img.shields.io/badge/Python-3.10%20|%203.11%20|%203.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Hardware%20Accelerated-007808?style=flat-square&logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-GPL%20v3.0-blueviolet?style=flat-square)](LICENSE)

<br/>

<p align="center">
  <b>CBML</b> (<i>CantarellaBots Mirror & Leech</i>) is a high-speed, enterprise-grade Telegram bot engineered for ultra-fast downloads, cloud synchronization, and automated video post-processing.<br/>
  Featuring an automated pipeline for <b>Watermarking</b>, <b>Video Transcoding (x264/x265 HEVC)</b>, <b>Audio Compression</b>, and <b>Multi-Cloud Mirroring</b>.
</p>

[✨ Features](#-core-features) • [🎬 Video Suite](#-video-transcoding--watermarking) • [🎮 Commands](#-command-reference) • [🚀 Quick Start](#-quick-deployment) • [👥 Community](#-community--support)

---

</div>

## 🌟 Core Features

### 🚀 Download & Transfer Engines
- **Torrent & Magnet**: High-concurrency downloads powered by **Aria2c** and **qBittorrent-nox**.
- **Direct Web Links**: Cloud resume, Instant DL, R2, Cloudflare workers, and multi-threaded streams.
- **Media Streaming**: 1,000+ streaming and social platforms supported via updated **yt-dlp**.
- **Usenet / NZB**: Fast NZB downloads supported via **SABnzbd**.
- **Debrid & Cloud Accounts**: Built-in support for **AllDebrid**, **Seedr**, and **Mega.nz**.

### ☁️ Cloud Mirror & Leech Destinations
- **Telegram Leech**: Supports 2GB (Bot) & 4GB (User Session) uploads with thumbnail generation.
- **Google Drive**: Service accounts, user tokens, shared drives, and index site link generation.
- **Rclone Integration**: 40+ cloud storage remotes (OneDrive, Dropbox, S3, WebDAV, etc.).
- **DDL UpHosters**: Multi-upload to **GoFile, Buzzheavier, PixelDrain, DevUploads, VikingFile**.

---

## 🎬 Video Transcoding & Watermarking

> [!NOTE]
> All video processing tasks execute in an automatic sequential pipeline:  
> **Download Complete ➔ Encode (x264/x265) ➔ Compress ➔ Watermark ➔ Auto-Merge ➔ Upload**

### 🏷️ 1. Watermark Engine
Protect and brand your media content with automated overlays:
- **Text Watermark**: Custom text or `@username` with customizable font size (e.g. `24`, `32`).
- **8 Color Palettes**: Choose from `White`, `Black`, `Red`, `Green`, `Blue`, `Yellow`, `Cyan`, `Magenta`, or any custom Hex code (`#RRGGBB`).
- **Image / Logo Overlay**: Upload your transparent PNG/JPG logo with automatic width scaling (`-150`, `150x50`).
- **9-Point Screen Positioning**:
  ```text
  ┌─────────────────┬───────────────────┬──────────────────┐
  │    Top-Left     │    Top-Center     │    Top-Right     │
  ├─────────────────┼───────────────────┼──────────────────┤
  │   Center-Left   │      Center       │   Center-Right   │
  ├─────────────────┼───────────────────┼──────────────────┤
  │   Bottom-Left   │   Bottom-Center   │   Bottom-Right   │
  └─────────────────┴───────────────────┴──────────────────┘
  ```

### 🗜️ 2. Smart Video Compressor
Reduce file size before uploading to avoid hitting Telegram upload boundaries:
- **CRF Control**: Tune compression levels (Default: `28`). Higher CRF = smaller size.
- **Speed Presets**: `ultrafast`, `faster`, `medium`, `slow`.
- **Audio Bitrate Optimization**: Downmix high-bitrate audio to `128k`, `96k`, or `64k` AAC.

### 🎞️ 3. Video Transcoder & Resolution Scaler
- **Modern Codecs**: Transcode to **H.264** (`libx264`) or **HEVC / H.265** (`libx265`) for superior quality-to-size ratio.
- **Resolution Downscaling**: Convert 4K/1080p content down to `1920x1080`, `1280x720`, or `854x480`.
- **Framerate Normalization**: Convert variable frame rates to fixed `24`, `30`, or `60` FPS.

### 🎧 4. Audio Arranging & Removing (`-tm` / Track Manager)
Take complete control over multi-audio and multi-subtitle media files with an interactive visual selector:
- **Rearrange Audio Tracks**: Change default audio priority (e.g. Move `Telugu` or `Hindi` or `English` to the #1 default audio position using `⬆️` and `⬇️` buttons).
- **Remove Unwanted Audio Streams**: Easily strip extra or unwanted language tracks with one click (`✓` / `✗` toggle).
- **Subtitle Management**: Select, keep, or purge unwanted subtitle languages.
- **Batch Processing**: Use **Apply to All** to instantly replicate your audio/subtitle track choices across entire anime or TV series batches.

---

## 🎮 Command Reference

### 📥 Mirror & Leech Tasks

| Command | Short | Description | Example |
| :--- | :---: | :--- | :--- |
| `/leech` | `/l` | Download and upload to Telegram | `/leech <url/magnet>` |
| `/mirror` | `/m` | Download and mirror to Cloud / Drive | `/mirror <url/magnet>` |
| `/qbleech` | `/ql` | Force download via qBittorrent | `/qbleech <magnet>` |
| `/ytdlleech` | `/yl` | Download video/playlist via yt-dlp | `/ytdlleech <youtube_link>` |
| `/speedtest` | `/spt` | Run server network speed and latency test | `/speedtest` |

### 🛠️ Useful Task Flags

Attach options directly to your `/leech` or `/mirror` commands:

```bash
# 🎧 Open Interactive Audio Arranger & Remover (Track Manager)
/leech <link> -tm

# Apply a custom FFmpeg transcode & delete original
/leech <link> -ff ["-i mltb.video -c:v libx265 -crf 26 -c:a aac -b:a 128k mltb -del"]

# Create a password-protected ZIP archive
/leech <link> -z mypassword123

# Rename output file
/leech <link> -n "Cantarella_Movie.mp4"

# Generate a 3x3 video screenshot grid
/leech <link> -tl 3x3

# Attach a custom thumbnail
/leech <link> -t https://images.site/thumb.jpg
```

---

## ⚙️ Interactive Settings Menus

### 👤 User Settings (`/usetting` or `/us`)
Send `/usetting` in bot chat to customize your personal preferences:
- **`ENC & COM & WATERMARK`**: Enable/disable personal video encoding, compression, and logo watermarks.
- **`Leech Settings`**: Configure custom thumbnails, thumbnail watermarks, and upload modes.
- **`Uphoster Settings`**: Toggle destination hosts (**GoFile**, **PixelDrain**, **Buzzheavier**, etc.).

### 📊 Task Manager & Limits (`/taskm` & `/taskuser`)
- **`/taskm`** *(Admin/Sudo)*: View live running tasks, manage queue slots, and set user limits.
- **`/taskuser`** *(Users)*: Check your active running tasks, queue position, and personal limits.

---

## 🚀 Quick Deployment

> [!CAUTION]
> ### ⚠️ Important Notice for Heroku Users
> **Deploying this bot on Heroku is strictly NOT recommended and can lead to immediate app termination or permanent account suspension** due to Heroku's Terms of Service against torrenting, continuous heavy network traffic, and high CPU encoding.
> 
> **Supported & Recommended Hosting Platforms:**
> CBML is heavily optimized for:
> - **Dedicated VPS / Cloud Servers** (Ubuntu / Debian on Hetzner, Contabo, DigitalOcean, Linode, AWS EC2, Oracle Cloud)
> - **Docker / Docker Compose Containers** (Local server, HomeLab, Unraid, TrueNAS)
> - **Alternative Container Clouds**: Koyeb, Render, Railway, CapRover, Fly.io, or Okteto

### Option A: Docker Deployment (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/abhinai2244/CBML.git
cd CBML

# 2. Configure credentials
cp configs/config_sample.py config.py
nano config.py

# 3. Start containers
docker compose up -d --build
```

### Option B: VPS Direct Setup (Ubuntu / Debian)

```bash
# 1. Install system dependencies
sudo apt-get update && sudo apt-get install -y python3-pip ffmpeg aria2 qbittorrent-nox rclone

# 2. Clone and install Python requirements
git clone https://github.com/abhinai2244/CBML.git
cd CBML
pip3 install -r requirements.txt

# 3. Launch Bot
bash start.sh
```

---

## 🔑 Environment Variables & `config.py`

| Variable | Required | Description |
| :--- | :---: | :--- |
| `BOT_TOKEN` | **Yes** | Telegram Bot Token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_API` | **Yes** | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_HASH` | **Yes** | Telegram API Hash from [my.telegram.org](https://my.telegram.org) |
| `OWNER_ID` | **Yes** | Your Telegram User ID |
| `DATABASE_URL` | Optional | MongoDB Database URI for persistent user configs |
| `ENABLE_WATERMARK` | Optional | Set `True` to allow watermark pipeline |
| `ENABLE_COMPRESS` | Optional | Set `True` to allow video compression pipeline |
| `ENABLE_ENCODE` | Optional | Set `True` to allow video encoding pipeline |

---

---

<div align="center">

## ⭐ Support & Feature Requests

**If you find this project helpful, please give it a ⭐ Star and 🍴 Fork!**  
This repository will be actively maintained and updated continuously with new features and optimizations.

> [!TIP]
> **Have a suggestion, idea, or feature request?**  
> Send it directly to my Telegram DM: [**@cantarella_wuwa**](https://t.me/cantarella_wuwa).  
> **I will definitely review and add your requested features for sure!** 🚀

---

## 👥 Community & Support

Have questions, suggestions, or want to report a bug? Join our official channels:

[![Telegram Channel](https://img.shields.io/badge/Join-CantarellaBots%20Channel-26A5E4?style=for-the-badge&logo=telegram)](https://t.me/cantarellabots)
[![Telegram Support](https://img.shields.io/badge/Contact-Tenka%20Izumo-EA4335?style=for-the-badge&logo=telegram)](https://t.me/cantarella_wuwa)

<sub>Crafted with ❤️ by <b>TENKA IZUMO</b> for the <b>CantarellaBots</b> Community.</sub>

</div>
