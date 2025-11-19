# api_py/docker_services.py (Güncellenmiş Hali)
from fastapi import APIRouter, HTTPException
import subprocess

router = APIRouter(
    prefix="/api/docker-services",
    tags=["docker-services"],
)

def _docker_ps():
    try:
        # stderr=subprocess.STDOUT ekledik ki hatayı yakalayabilelim
        out = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.ID}};{{.Names}};{{.Image}};{{.Status}}"],
            text=True,
            stderr=subprocess.STDOUT 
        )
    except FileNotFoundError:
        # Docker hiç yüklü değilse veya PATH'de yoksa
        raise HTTPException(status_code=500, detail="Docker komutu bulunamadı. Docker yüklü mü?")
    except subprocess.CalledProcessError as exc:
        # Docker komutu çalıştı ama hata verdi (Örn: Yetki hatası)
        hata_mesaji = exc.output.strip() if exc.output else str(exc)
        print(f"DOCKER HATASI: {hata_mesaji}") # Terminalde görmek için
        
        # BURASI ÖNEMLİ: detail kısmına str() koymazsan 500 hatası almaya devam edersin
        raise HTTPException(status_code=500, detail=f"Docker hatası: {hata_mesaji}")
    except Exception as e:
        print(f"GENEL HATA: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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