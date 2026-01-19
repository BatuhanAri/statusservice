# api_py/docker_logs.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import docker
from pathlib import Path
import json
from typing import AsyncIterator, List, Optional

router = APIRouter(
    prefix="/api/docker-logs",
    tags=["docker-logs"],
)

# tail: 0 veya negatif verilirse -> tüm satırlar
DEFAULT_TAIL = 0


def read_log_file_lines(path: Path, tail: int) -> List[str]:
    """
    Docker 'json-file' log dosyasını satır satır okur.
    Her satır JSON olduğu için 'log' alanını döndürür.    
    tail > 0 ise, sadece son 'tail' satırı döndürür.
    """
    if not path.exists():
        raise FileNotFoundError(f"Log dosyası bulunamadı: {path}")

    raw_lines: List[str] = []

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                msg = (obj.get("log") or "").rstrip("\n")
                raw_lines.append(msg)
            except json.JSONDecodeError:
                # Beklenmedik bir format varsa, satırı olduğu gibi koy
                raw_lines.append(line)

    if tail and tail > 0 and len(raw_lines) > tail:
        return raw_lines[-tail:]

    return raw_lines

# Belirtilen log satırını parse eder, zaman damgası ve log mesajını ayırır
def parse_log_line(raw_line: str) -> Optional[str]:
    line = raw_line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
        msg = (obj.get("log") or "").rstrip("\n")
        return msg
    except json.JSONDecodeError:
        return line

# SSE formatında mesaj paketler
def _sse_pack(message: str) -> str:
    clean = message.replace("\r", "")
    return "".join(f"data: {line}\n" for line in clean.split("\n")) + "\n"

@router.get("/{container_name}")
def get_docker_logs(container_name: str, tail: int = DEFAULT_TAIL):
    """
    Belirtilen Docker container'ın log-driver'ı json-file ise,
    /var/lib/docker/containers/<ID>/<ID>-json.log dosyasından
    logları okur ve satır listesi döndürür.

    tail > 0 ise sadece son 'tail' satır, 0 veya negatif ise tüm satırlar.
    """
    try:
        client = docker.from_env()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docker'a bağlanılamadı: {e}")

    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container bulunamadı: {container_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Container okunamadı: {e}")

    # docker inspect ile gelen metadata
    attrs = getattr(container, "attrs", {}) or {}
    log_path_str = attrs.get("LogPath")

    if not log_path_str:
        # Bazı custom log-driver'larda LogPath boş olabilir
        raise HTTPException(
            status_code=500,
            detail="Bu container için LogPath bilgisi bulunamadı (json-file log-driver kullanmıyor olabilir).",
        )

    log_path = Path(log_path_str)

    try:
        lines = read_log_file_lines(log_path, tail)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Log dosyası okunamadı: {e}")

    return {
        "container": container_name,
        "tail": tail,
        "count": len(lines),
        "lines": lines,
    }

# Canlı log akışı için SSE endpoint
@router.get("/{container_name}/stream")
async def stream_docker_logs(container_name: str, tail: int = 200):
    """
    Docker container loglarını SSE (text/event-stream) olarak canlı yayında döndürür.
    tail > 0 ise önce son tail satırı gönderir, sonra yeni satırları takip eder.
    """
    try:
        client = docker.from_env()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docker'a bağlanılamadı: {e}")

    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container bulunamadı: {container_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Container okunamadı: {e}")

    attrs = getattr(container, "attrs", {}) or {}
    log_path_str = attrs.get("LogPath")

    if not log_path_str:
        raise HTTPException(
            status_code=500,
            detail="Bu container için LogPath bilgisi bulunamadı (json-file log-driver kullanmıyor olabilir).",
        )

    log_path = Path(log_path_str)

    # SSE event stream generator
    async def event_stream() -> AsyncIterator[str]:
        try:
            if tail and tail > 0:
                for line in read_log_file_lines(log_path, tail):
                    yield _sse_pack(line)
        except Exception:
            yield _sse_pack("Log dosyası okunamadı.")

        try:
            with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(0, 2)
                while True:
                    raw_line = handle.readline()
                    if not raw_line:
                        await asyncio.sleep(0.5)
                        continue
                    parsed = parse_log_line(raw_line)
                    if parsed:
                        yield _sse_pack(parsed)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_stream(), media_type="text/event-stream")
