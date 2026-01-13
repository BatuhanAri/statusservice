import asyncio, shlex
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

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

# Belirtilen mesajı SSE formatına çevirir
def _sse_pack(message: str) -> str:
    clean = message.replace("\r", "")
    return "".join(f"data: {line}\n" for line in clean.split("\n")) + "\n"

# Belirtilen service_id için service unit adını döner
def _find_service_unit(service_id: str) -> Optional[str]:
    for svc in SERVICES:
        if svc["id"] == service_id:
            return svc["unit"]
    return None

# Uygun journal dizinini seçer
def _select_journal_dir() -> Optional[str]:
    for d in JOURNAL_DIRS:
        if d is None:
            continue
        if Path(d).is_dir():
            return d
    return None

# Tüm system service loglarını döner
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

# Belirtilen service_id için system log akışı döner
@router.get("/stream/{service_id}")
async def stream_system_logs(service_id: str, tail: int = 200):
    unit = _find_service_unit(service_id)
    if not unit:
        raise HTTPException(status_code=404, detail=f"System service bulunamadı: {service_id}")

    # Canlı log akışı için SSE endpoint
    async def event_stream() -> AsyncIterator[str]:
        journal_dir = _select_journal_dir()
        # journalctl komutunu hazırla
        if journal_dir:
            cmd = (
                f"journalctl -D {shlex.quote(journal_dir)} "
                f"-u {shlex.quote(unit)} "
                f"-n {int(tail)} -f --no-pager --output=short"
            )
        else:
            cmd = (
                f"journalctl -u {shlex.quote(unit)} "
                f"-n {int(tail)} -f --no-pager --output=short"
            )
        # Log akış süreci başlat
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Log satırlarını oku ve SSE formatında yayınla
        try:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    await asyncio.sleep(0.2)
                    continue
                text = line.decode(errors="replace").rstrip("\n")
                if text:
                    yield _sse_pack(text)
        except asyncio.CancelledError:
            proc.terminate()
            return
        finally:
            proc.terminate()

    return StreamingResponse(event_stream(), media_type="text/event-stream")