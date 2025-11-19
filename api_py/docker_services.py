# api_py/docker_services.py (Güncellenmiş Hali)
from fastapi import APIRouter, HTTPException
import subprocess

router = APIRouter(
    prefix="/api/docker-services",
    tags=["docker-services"],
)

def _docker_ps():
    try:
        # Artık direkt "docker" yazabilirsin, çünkü apt-get ile kuruldu ve PATH'de var.
        out = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.ID}};{{.Names}};{{.Image}};{{.Status}}"],
            text=True,
            stderr=subprocess.STDOUT
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Docker komutu bulunamadı (Build sorunu olabilir).")
    except subprocess.CalledProcessError as exc:
        msg = exc.output.strip()
        # Eğer "permission denied" derse socket mount edilmemiştir.
        raise HTTPException(status_code=500, detail=f"Docker Hatası: {msg}")
    
    # ... parse işlemleri aynı ...
    return [] # Parse edilmiş listeyi dön

    items = []
    if not out:
        return items

    for line in out.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split(";", 3)
        if len(parts) != 4: continue
        
        cid, name, image, status = parts
        items.append({
            "id": cid,
            "name": name,
            "image": image,
            "status": status,
            "running": status.lower().startswith("up"),
            "kind": "docker",
        })
    return items

@router.get("")
def list_docker_services():
    return _docker_ps()