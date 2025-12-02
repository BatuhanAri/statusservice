import asyncio, shlex
from typing import Any, Dict, List
from fastapi import APIRouter

router = APIRouter(
    prefix="/api/system-logs",
    tags=["system-logs"])

SERVICES = [
    {
        "id": "bind9",
        "unit": "named.service",
        "name": "BIND9 DNS",
    },
    {
        "id": "kea",
        "unit": "kea-dhcp4-server.service",
        "name": "Kea DHCPv4",
    },
    {
        "id": "nginx",
        "unit": "nginx.service",
        "name": "Nginx Reverse Proxy",
    },
    {
        "id": "system-service",
        "unit": "system-service.service",
        "name": "IFE System Service",
    },
]

async def _run(cmd: str) -> str:
    """journalctl komutunu async çalıştır"""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        # journalctl yoksa veya o unit için log yoksa hata dönmesin,
        # çıktıya sadece hata mesajını yazalım.
        msg = (err or out).decode(errors="replace").strip()
        return f"[ERROR] {msg or 'journalctl komutu başarısız'}"
    return out.decode(errors="replace")


@router.get("")
async def get_all_system_logs(lines: int = 80):
    """
    Tüm tanımlı systemd servislerinin son X satır logunu döner.
    /api/system-logs?lines=100 gibi kullanılabilir.
    """
    items: List[Dict[str, Any]] = []

    for svc in SERVICES:
        unit = svc["unit"]
        # journalctl -u unit -n lines --no-pager --output=short
        cmd = (
            f"journalctl -u {shlex.quote(unit)} "
            f"-n {int(lines)} --no-pager --output=short"
        )
        logs = await _run(cmd)

        items.append(
            {
                "id": svc["id"],
                "name": svc["name"],
                "unit": unit,
                "lines": lines,
                "logs": logs,
            }
        )

    return {"items": items, "lines": lines}