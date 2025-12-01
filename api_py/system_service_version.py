from fastapi import APIRouter
from pathlib import Path
from typing import Optional
import re

UNIT_FILE = Path("/etc/systemd/system/system-service.service")
VERSION_RE = re.compile(r"\(v([^)]+)\)")

def get_system_service_version() -> Optional[str]:
    try:
        text = UNIT_FILE.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return None

    desc = None
    for line in text.splitlines():
        if line.startswith("Description="):
            desc = line.split("=", 1)[1].strip()
            break

    if not desc:
        return None

    m = VERSION_RE.search(desc)
    if not m:
        return None

    return m.group(1)  # 2025-11-26-e3bd4f3


router = APIRouter(prefix="/api/system-service", tags=["system-service"])

@router.get("/version")
async def system_service_version():
    version = get_system_service_version()
    return {"version": version}
