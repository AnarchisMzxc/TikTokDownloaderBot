import os
from dataclasses import dataclass

from dotenv import load_dotenv
load_dotenv()

@dataclass(frozen=True)
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
    max_workers: int = int(os.getenv("MAX_WORKERS", "3"))
    queue_max_size: int = int(os.getenv("QUEUE_MAX_SIZE", "100"))
    download_dir: str = os.getenv("DOWNLOAD_DIR", "./downloads")
    max_file_size_mb: int = 50
    max_video_height: int = int(os.getenv("MAX_VIDEO_HEIGHT", "1080"))
    admin_id: int = int(os.getenv("ADMIN_ID", "0"))
    tiktok_backend: str = os.getenv("TIKTOK_BACKEND", "auto")
    storage_chat_id: int = int(os.getenv("STORAGE_CHAT_ID", "0"))
    cookies_file: str = os.getenv("COOKIES_FILE", "")
    proxy_url: str = os.getenv("PROXY_URL", "")

    supported_hosts = (
        "youtube.com", "youtu.be",
        "instagram.com",
        "tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
        "pinterest.com", "pin.it",
    )

    @property
    def effective_storage_chat_id(self) -> int:
        return self.storage_chat_id or self.admin_id

cfg = Config()
os.makedirs(cfg.download_dir, exist_ok=True)