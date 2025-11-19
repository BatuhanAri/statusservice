from fastapi import APIRouter, HTTPException
import subprocess
import shutil

router = APIRouter(
    prefix="/api/docker-services",
    tags=["docker-services"],
)

def _docker_ps():
    """
    docker ps -a çıktısını sade bir JSON'a çevirir.
    """
    
    # 1. Docker komutunun yolunu bulalım (Güvenlik ve Path sorunları için)
    docker_path = shutil.which("docker")
    if not docker_path:
        raise HTTPException(status_code=500, detail="Docker sunucuda yüklü değil veya PATH'de bulunamadı.")

    try:
        out = subprocess.check_output(
            [
                docker_path, # "docker" yerine tam yolu kullanmak daha güvenlidir
                "ps",
                "-a",
                "--format",
                "{{.ID}};{{.Names}};{{.Image}};{{.Status}}",
            ],
            text=True,
            stderr=subprocess.STDOUT # Hata mesajlarını da yakalamak için
        )
    except subprocess.CalledProcessError as exc:
        # Hata çıktısını (output) alıp loglayalım
        error_msg = exc.output.strip() if exc.output else str(exc)
        print(f"Docker Komut Hatası: {error_msg}")
        
        # Detail kısmına str() ekleyerek JSON hatasını önlüyoruz
        raise HTTPException(
            status_code=500, 
            detail=f"Docker komutu çalıştırılamadı. Yetki hatası olabilir: {error_msg}"
        )
    except Exception as e:
        print(f"Beklenmeyen Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    items = []
    # Çıktı boşsa hata vermesin
    if not out:
        return items

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(";", 3)
        if len(parts) != 4:
            continue
        
        cid, name, image, status = parts
        # Status genelde "Up 2 hours" veya "Exited (0)" şeklindedir.
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