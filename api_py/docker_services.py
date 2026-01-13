import time
import docker
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/docker-services", tags=["docker-services"])

# Docker client objesini döner, erişilemiyorsa 500 hatası fırlatır
def _client():
    try:
        c = docker.from_env()
        c.ping()
        return c
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docker daemon erişilemiyor: {e}")
    
# Belirtilen ref (name veya full id) ile container objesini döner
def _get_container(client, ref: str):
    try:
        # ref = full id veya name kullan.
        return client.containers.get(ref)
    except docker.errors.NotFound as e:
        raise HTTPException(status_code=404, detail="Container bulunamadı (name veya full id gönder).") from e
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=f"Docker hatası: {e}") from e

# Container state bilgisini döner
def _state(container):
    container.reload()
    st = container.attrs.get("State", {}) or {}
    status = st.get("Status")              # running/exited/restarting/...
    health = (st.get("Health") or {}).get("Status")  # healthy/unhealthy/starting
    exit_code = st.get("ExitCode")
    err = st.get("Error")
    return status, health, exit_code, err

# Belirtilen predicate fonksiyonu timeout süresi içinde True dönerse True, aksi halde False döner
def _wait(container, predicate, timeout=20, poll=0.5):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = predicate()
        if last:
            return True
        time.sleep(poll)
    return False

# Container loglarının son n satırını döner
def _tail_logs(container, n=80):
    try:
        return container.logs(tail=n).decode("utf-8", errors="replace")
    except Exception:
        return ""
    
# Tüm docker containerları listeler
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

# Stop-Start endpointi
@router.post("/{ref}/stop-start")
def stop_start_container(ref: str):
    client = _client()
    container = _get_container(client, ref)

    status, health, exit_code, err = _state(container)

    # Eğer çalışıyorsa önce STOP et
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
        
        # Durduktan sonra state al
        return {"id": container.id, "name": container.name, "status": s, "health": h}


    # START
    # Böylece hem durmuş olanlar başlar, hem de yukarıda durdurduklarımız tekrar başlar.
    try:
        container.start()
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Start komutu verilemedi: {e}")

    # Çalıştığından emin ol
    ok = _wait(container, lambda: _state(container)[0] == "running", timeout=30)
    s, h, ec, er = _state(container)

    # Sadece 'ok' False ise hata fırlatıyoruz.
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

# Tek tek start/stop için endpointler de ekleme
@router.post("/{ref}/start")
def start_container(ref: str):
    client = _client()
    container = _get_container(client, ref)

    status, health, exit_code, err = _state(container)
    if status == "running":
        return {"id": container.id, "name": container.name, "status": status, "health": health}

    try:
        container.start()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Start komutu verilemedi: {e}")

    ok = _wait(container, lambda: _state(container)[0] == "running", timeout=30)
    s, h, ec, er = _state(container)
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

# Tek tek start/stop için endpointler de ekleme
@router.post("/{ref}/restart")
def restart_container(ref: str):
    client = _client()
    container = _get_container(client, ref)

    try:
        container.restart(timeout=3)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restart komutu verilemedi: {e}")

    ok = _wait(container, lambda: _state(container)[0] == "running", timeout=30)
    s, h, ec, er = _state(container)
    if not ok:
        logs = _tail_logs(container, n=120)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Container restart sonrası running durumuna gelemedi (muhtemel crash/config/port hatası).",
                "status": s, "health": h, "exit_code": ec, "error": er,
                "logs_tail": logs[-4000:],
            },
        )

    return {"id": container.id, "name": container.name, "status": s, "health": h}


# Tek tek start/stop için endpointler de ekleme
@router.post("/{ref}/stop")
def stop_container(ref: str):
    client = _client()
    container = _get_container(client, ref)

    status, health, exit_code, err = _state(container)
    if status not in ("running", "restarting"):
        return {"id": container.id, "name": container.name, "status": status, "health": health}

    try:
        container.stop(timeout=15)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stop komutu verilemedi: {e}")

    ok = _wait(container, lambda: _state(container)[0] == "exited", timeout=30)
    s, h, ec, er = _state(container)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Container stop tamamlanmadı (timeout).",
                "status": s, "health": h, "exit_code": ec, "error": er,
            },
        )

    return {"id": container.id, "name": container.name, "status": s, "health": h}