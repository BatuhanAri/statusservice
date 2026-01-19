from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import docker
from pathlib import Path
import json
import re  # Regex kütüphanesini ekledik
from typing import AsyncIterator, List, Optional

router = APIRouter(
    prefix="/api/docker-logs",
    tags=["docker-logs"],
)

# tail: 0 veya negatif verilirse -> tüm satırlar
DEFAULT_TAIL = 0

# ANSI renk kodlarını yakalayan regex deseni
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def format_log_entry(raw_line: str) -> Optional[str]:
    """
    Ham JSON satırını parse eder:
    1. Zaman damgasını düzeltir.
    2. ANSI renk kodlarını (çöp karakterleri) temizler.
    3. [YYYY-MM-DD HH:MM:SS] [INFO] Mesaj formatına sokar.
    """
    line = raw_line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
        # Log mesajını al
        msg = (obj.get("log") or "").rstrip()
        
        # 1. ADIM: ANSI Renk Kodlarını Temizle (Burası sorunu çözer)
        # "[[34;1mINFO[0;22m]" -> "[INFO]" olur.
        clean_msg = ANSI_ESCAPE.sub('', msg)
        
        return clean_msg
    except json.JSONDecodeError:
        # JSON bozuksa satırı olduğu gibi ama temizleyerek dön
        return ANSI_ESCAPE.sub('', line)

def read_log_file_lines(path: Path, tail: int) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Log dosyası bulunamadı: {path}")

    formatted_lines: List[str] = []

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            formatted = format_log_entry(line)
            if formatted:
                formatted_lines.append(formatted)

    if tail and tail > 0 and len(formatted_lines) > tail:
        return formatted_lines[-tail:]

    return formatted_lines

# SSE formatında mesaj paketler
def _sse_pack(message: str) -> str:
    clean = message.replace("\r", "")
    return "".join(f"data: {line}\n" for line in clean.split("\n")) + "\n"

# Belirtilen container'ın loglarının son n satırını döner
@router.get("/{container_name}")
def get_docker_logs(container_name: str, tail: int = DEFAULT_TAIL):
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    attrs = getattr(container, "attrs", {}) or {}
    log_path_str = attrs.get("LogPath")

    if not log_path_str:
        raise HTTPException(status_code=500, detail="LogPath bulunamadı.")

    log_path = Path(log_path_str)

    try:
        lines = read_log_file_lines(log_path, tail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "container": container_name,
        "tail": tail,
        "count": len(lines),
        "lines": lines,
    }

# Belirtilen container'ın log akışı döner
@router.get("/{container_name}/stream")
async def stream_docker_logs(container_name: str, tail: int = 200):
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    attrs = getattr(container, "attrs", {}) or {}
    log_path_str = attrs.get("LogPath")

    if not log_path_str:
        raise HTTPException(status_code=500, detail="LogPath bulunamadı.")

    log_path = Path(log_path_str)

    async def event_stream() -> AsyncIterator[str]:
        # Geçmiş loglar
        try:
            if tail and tail > 0:
                for line in read_log_file_lines(log_path, tail):
                    yield _sse_pack(line)
        except Exception:
            yield _sse_pack("Log geçmişi okunamadı.")

        # Canlı loglar
        try:
            with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(0, 2)
                while True:
                    raw_line = handle.readline()
                    if not raw_line:
                        await asyncio.sleep(0.5)
                        continue
                    
                    formatted = format_log_entry(raw_line)
                    if formatted:
                        yield _sse_pack(formatted)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_stream(), media_type="text/event-stream")