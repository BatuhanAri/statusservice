# api_py/docker_logs.py
from fastapi import APIRouter, HTTPException
import docker

router = APIRouter(
    prefix="/api/docker-logs",
    tags=["docker-logs"],
)

# NEDEN tail=800?
# - Loglar bazen çok büyük olabiliyor (MB'lerce)
# - İlk adımda sadece son X satırı almak, hem hızlı hem yeterli
DEFAULT_TAIL = 800

@router.get("/{container_name}")
def get_docker_logs(container_name: str, tail: int = DEFAULT_TAIL):
    """
    Belirtilen Docker container'ın son 'tail' satır logunu döndürür.
    Şimdilik geleni olduğu gibi, satır satır bir liste olarak yolluyoruz.
    """
    try:
        client = docker.from_env()
    except Exception as e:
        # Örneğin docker.sock mount edilmemişse vs.
        raise HTTPException(status_code=500, detail=f"Docker'a bağlanılamadı: {e}")

    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container bulunamadı: {container_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Container okunamadı: {e}")

    try:
        raw = container.logs(
            tail=tail,
            timestamps=True,  # NEDEN? Log satırında saat olsun istiyoruz
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Loglar alınamadı: {e}")

    # bytes -> string
    text = raw.decode("utf-8", errors="ignore")
    lines = [line for line in text.splitlines() if line.strip()]

    return {
        "container": container_name,
        "tail": tail,
        "count": len(lines),
        "lines": lines,   # frontend burada pagination yapacak
    }
