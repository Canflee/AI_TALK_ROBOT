import subprocess
import sys


def _is_running(image_name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=10,
        )
    except Exception:
        return False
    return image_name.lower() in (result.stdout or "").lower()


def check_weixin4() -> str:
    if sys.platform != "win32":
        return "微信 4.x 方案仅支持 Windows 平台"
    if not _is_running("Weixin.exe"):
        return "未检测到微信 4.x 正在运行，请先启动并登录微信"
    return ""
