# api_py/docker_services.py
from fastapi import APIRouter, HTTPException
import subprocess

router = APIRouter(
    prefix="/api/docker-services",
    tags=["docker-services"],
)


def _docker_ps():
    """
    docker ps -a çıktısını sade bir JSON'a çevirir.
    docker ps -a --format '{{.ID}};{{.Names}};{{.Image}};{{.Status}}'
    """
    try:
        out = subprocess.check_output(
            [
                "docker",
                "ps",
                "-a",
                "--format",
                "{{.ID}};{{.Names}};{{.Image}};{{.Status}}",
            ],
            text=True,
        )
    except FileNotFoundError as err:
        print(f"Hata: {err}")
        raise HTTPException(status_code=500, detail=err)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=f"docker ps -a hatası: {exc}")  # type: ignore

    items = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(";", 3)
        if len(parts) != 4:
            continue
        cid, name, image, status = parts
        running = status.lower().startswith("up")
        items.append(
            {
                "id": cid,
                "name": name,
                "image": image,
                "status": status,
                "running": running,
                "kind": "docker",
            }
        )
    return items


@router.get("")
def list_docker_services():
    """
    GET /api/docker-services
    """
    return _docker_ps()
