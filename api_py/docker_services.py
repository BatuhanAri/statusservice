import docker
from fastapi import APIRouter, HTTPException
import os

router = APIRouter(
    prefix="/api/docker-services",
    tags=["docker-services"],
)

@router.get("")
def list_docker_services():
    """
    Docker soketi üzerinden aktif konteynerleri listeler.
    """
    try:
        # Docker istemcisini başlat (Ortam değişkenlerinden veya soketten otomatik algılar)
        client = docker.from_env()
        
        containers = client.containers.list(all=True)
        items = []
        
        for c in containers:
            # İsim temizliği (Docker API bazen isimlerin başına / koyar)
            name = c.name.lstrip("/")
            
            # Resim etiketi kontrolü
            image_tag = c.image.tags[0] if c.image.tags else "unknown-image"
            
            items.append({
                "id": c.short_id,
                "name": name,
                "image": image_tag,
                "status": c.status,
                "running": c.status == "running",
                "kind": "docker",
            })
            
        return items

    except docker.errors.DockerException as e:
        print(f"Docker Bağlantı Hatası: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Docker daemon'a bağlanılamadı. Socket bağlı mı? Hata: {str(e)}"
        )
    except Exception as e:
        print(f"Genel Hata: {e}")
    raise HTTPException(status_code=500, detail=str(e))

# Yardımcı fonksiyon: Konteyneri isme göre al
def _get_container(client, container_name: str):
    try:
        return client.containers.get(container_name)
    except docker.errors.NotFound as e:
        raise HTTPException(status_code=404, detail="Docker container bulunamadı.") from e
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=f"Docker hatası: {e}") from e

# Konteyneri durdur ve tekrar başlat
@router.post("/{container_name}/stop-start")
def stop_start_container(container_name: str):
    try:
        client = docker.from_env()
        container = _get_container(client, container_name)
        container.reload()
        if container.status == "running":
            container.stop(timeout=10)
        container.start()
        container.reload()
        return {
            "name": container_name,
            "status": container.status,
        }
    except HTTPException:
        raise
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=f"Docker hatası: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

# Konteyneri yeniden başlat
@router.post("/{container_name}/restart")
def restart_container(container_name: str):
    try:
        client = docker.from_env()
        container = _get_container(client, container_name)
        container.restart(timeout=1)
        container.reload()
        return {
            "name": container_name,
            "status": container.status,
        }
    except HTTPException:
        raise
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=f"Docker hatası: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e