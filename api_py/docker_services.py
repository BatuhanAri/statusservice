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