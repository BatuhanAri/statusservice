import time
import docker
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/docker-services", tags=["docker-services"])

def _client():
    try:
        c = docker.from_env()
        c.ping()
        return c
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docker daemon erişilemiyor: {e}")

def _get_container(client, ref: str):
    try:
        # ref = full id veya name kullan.
        return client.containers.get(ref)
    except docker.errors.NotFound as e:
        raise HTTPException(status_code=404, detail="Container bulunamadı (name veya full id gönder).") from e
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=f"Docker hatası: {e}") from e

def _state(container):
    container.reload()
    st = container.attrs.get("State", {}) or {}
    status = st.get("Status")              # running/exited/restarting/...
    health = (st.get("Health") or {}).get("Status")  # healthy/unhealthy/starting
    exit_code = st.get("ExitCode")
    err = st.get("Error")
    return status, health, exit_code, err

def _wait(container, predicate, timeout=20, poll=0.5):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = predicate()
        if last:
            return True
        time.sleep(poll)
    return False

def _tail_logs(container, n=80):
    try:
        return container.logs(tail=n).decode("utf-8", errors="replace")
    except Exception:
        return ""

@router.get("")
def list_docker_services():
    client = _client()
    items = []
    for c in client.containers.list(all=True):
        c.reload()
        st = c.attrs.get("State", {}) or {}
        items.append({
            "id": c.id,                 # FULL ID
            "name": c.name,
            "image": (c.image.tags[0] if c.image.tags else "unknown-image"),
            "status": st.get("Status"),
            "health": (st.get("Health") or {}).get("Status"),
            "running": st.get("Status") == "running",
            "kind": "docker",
        })
    return items

@router.post("/{ref}/stop-start")
def stop_start_container(ref: str):
    client = _client()
    container = _get_container(client, ref)

    status, health, exit_code, err = _state(container)

    # 1) Eğer çalışıyorsa önce STOP et
    if status in ("running", "restarting"):
        container.stop(timeout=15)

        # Durduğundan emin ol
        ok = _wait(container, lambda: _state(container)[0] == "exited", timeout=30)
        
        # Eğer durmazsa hata ver
        if not ok:
            s, h, ec, er = _state(container)
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Container stop tamamlanmadı (timeout).",
                    "status": s, "health": h, "exit_code": ec, "error": er
                },
            )

    # 2) START (Burayı 'else' içinden çıkardık, ana akışa aldık)
    # Böylece hem durmuş olanlar başlar, hem de yukarıda durdurduklarımız tekrar başlar.
    try:
        container.start()
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Start komutu verilemedi: {e}")

    # 3) Çalıştığından emin ol
    ok = _wait(container, lambda: _state(container)[0] == "running", timeout=30)
    s, h, ec, er = _state(container)

    # BURADAKİ HATA DÜZELTİLDİ: Sadece 'ok' False ise hata fırlatıyoruz.
    if not ok:
        logs = _tail_logs(container, n=120)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Container running durumuna gelemedi (muhtemel crash/config/port hatası).",
                "status": s, "health": h, "exit_code": ec, "error": er,
                "logs_tail": logs[-4000:], 
            },
        )

    return {"id": container.id, "name": container.name, "status": s, "health": h}