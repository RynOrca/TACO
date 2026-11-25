import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

for _p in (PROJECT_ROOT / ".env", BASE_DIR / ".env"):
    if _p.exists():
        load_dotenv(_p)
        break

_DEFAULT_DB = PROJECT_ROOT / "database" / "chat.db"
DB_PATH = os.getenv("CHAT_DB_PATH", str(_DEFAULT_DB))


def _int(name: str, default: int) -> int:
    """环境变量转 int，空值或非法值回退默认，避免 int('') 让服务起不来。"""
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        print(f"[config] {name}={raw!r} 不是整数，使用默认值 {default}")
        return default


HOST = os.getenv("CHAT_HOST", "0.0.0.0")
PORT = _int("CHAT_PORT", 10086)

# 图片消息：图片文件走内置 HTTP 服务上传/下载，聊天消息里只传文件名
IMAGE_DIR = Path(os.getenv("CHAT_IMAGE_DIR", str(Path(DB_PATH).parent / "images")))
IMAGE_PORT = _int("CHAT_IMAGE_PORT", 10087)
IMAGE_MAX_BYTES = _int("CHAT_IMAGE_MAX_BYTES", 8 * 1024 * 1024)
# 通用附件：白名单后缀（图片另按 Content-Type 判定）+ 单文件上限
FILE_MAX_BYTES = _int("CHAT_FILE_MAX_BYTES", 20 * 1024 * 1024)
FILE_EXT_ALLOWED = tuple(
    ext.strip().lower() for ext in os.getenv(
        "CHAT_FILE_EXTS",
        ".pdf,.zip,.txt,.md,.csv,.log,.json,.doc,.docx,.xls,.xlsx,.ppt,.pptx,"
        ".py,.js,.ts,.java,.c,.cpp,.h,.sql,.patch,.mp3,.mp4,.wav,.png,.jpg,.jpeg,.gif,.webp",
    ).split(",") if ext.strip()
)

# 管理员（能禁言别人）：逗号分隔，留空则没人有权限
ADMIN_USERS = [name.strip() for name in os.getenv("ADMIN_USERS", "").split(",") if name.strip()]

AGENT_TIMEOUT = _int("AGENT_TIMEOUT", 60)
AGENT_MAX_STEPS = _int("AGENT_MAX_STEPS", 5)
MAX_HISTORY = _int("MAX_HISTORY", 20)

# Agent 定时总结：默认关闭，0 表示不自动跑；客户端也能用 /auto 分钟 临时开启
AGENT_AUTO_SUMMARY_SECONDS = _int("AGENT_AUTO_SUMMARY_SECONDS", 0)
AGENT_AUTO_SUMMARY_MIN_MESSAGES = _int("AGENT_AUTO_SUMMARY_MIN_MESSAGES", 3)

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
