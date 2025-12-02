import asyncio, shlex
from typing import Any, Dict, List
from fastapi import APIRouter

# Ubuntu'da runtime journal genelde /run/log/journal,
# persistent açıksa /var/log/journal da olur.
JOURNAL_DIRS = [
    "/run/log/journal",
    "/var/log/journal",
    None,  # son çare: journalctl'ı default paths ile çalıştır
]

router = APIRouter(
    prefix="/api/system-logs",
    tags=["system-logs"],
)

SERVICES = [
    {"id": "bind9",          "unit": "named.service",                  "name": "BIND9 DNS"},
    {"id": "kea",            "unit": "kea-dhcp4-server.service",       "name": "Kea DHCPv4"},
    {"id": "nginx",          "unit": "nginx.service",                  "name": "Nginx Reverse Proxy"},
    {"id": "system-service", "unit": "system-service.service",         "name": "IFE System Service"},
]


async def _run(cmd: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        msg = (err or out).decode(errors="replace").strip()
        return f"[ERROR] {msg or 'journalctl komutu başarısız'}"
    return out.decode(errors="replace")


async def _get_logs_for_unit(unit: str, lines: int) -> str:
    """
    Aynı unit için sırayla:
      /run/log/journal
      /var/log/journal
      (sonra defaults)
    üzerinde dene.
    İlk "gerçek" sonuçta dur.
    """
    last_output = ""
    for d in JOURNAL_DIRS:
        if d:
            cmd = (
                f"journalctl -D {shlex.quote(d)} "
                f"-u {shlex.quote(unit)} "
                f"-n {int(lines)} --no-pager --output=short"
            )
        else:
            cmd = (
                f"journalctl -u {shlex.quote(unit)} "
                f"-n {int(lines)} --no-pager --output=short"
            )

        out = await _run(cmd)
        last_output = out

        # journalctl hiç kayıt bulamazsa kelimenin tam anlamıyla "-- No entries --" basar
        if "-- No entries --" not in out and "[ERROR]" not in out:
            return out

    # Hiçbirinde log bulamazsak, son çıktıyı döneriz (muhtemelen "-- No entries --")
    return last_output


@router.get("")
async def get_all_system_logs(lines: int = 80):
    items: List[Dict[str, Any]] = []

    for svc in SERVICES:
        unit = svc["unit"]
        logs = await _get_logs_for_unit(unit, lines)

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
