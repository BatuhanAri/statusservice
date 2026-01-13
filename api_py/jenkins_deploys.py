import asyncio
import os
import re
from datetime import date, timedelta, datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


def _compile_regex(pattern: Optional[str], label: str) -> Optional[re.Pattern[str]]:
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise HTTPException(status_code=400, detail=f"{label} regex hatası: {exc}")


def _daterange(days: int) -> List[date]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    return [start + timedelta(days=offset) for offset in range(days)]


@router.get("/api/jenkins/deploys")
async def jenkins_deploys(
    days: int = Query(7, ge=1, le=60),
    max_builds: int = Query(200, ge=1, le=2000),
    include: Optional[str] = None,
    exclude: Optional[str] = None,
    success_only: bool = True,
):
    base_url = os.getenv("JENKINS_URL")
    if not base_url:
        raise HTTPException(status_code=503, detail="JENKINS_URL tanımlı değil")

    base_url = base_url.rstrip("/")
    include = include or os.getenv("JENKINS_JOB_REGEX")

    include_re = _compile_regex(include, "include")
    exclude_re = _compile_regex(exclude, "exclude")

    user = os.getenv("JENKINS_USER")
    token = os.getenv("JENKINS_TOKEN") or os.getenv("JENKINS_PASSWORD")
    auth = (user, token) if user and token else None

    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            jobs_resp = await client.get(
                f"{base_url}/api/json",
                params={"tree": "jobs[name,url]"},
                headers=headers,
                auth=auth,
            )
            jobs_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Jenkins API erişilemedi: {exc}")

        payload = jobs_resp.json()
        jobs = payload.get("jobs", [])

        filtered_jobs = []
        for job in jobs:
            name = job.get("name")
            if not name:
                continue
            if include_re and not include_re.search(name):
                continue
            if exclude_re and exclude_re.search(name):
                continue
            filtered_jobs.append(job)

        sem = asyncio.Semaphore(5)

        async def fetch_builds(job: Dict[str, Any]) -> Dict[str, Any]:
            job_url = job.get("url")
            name = job.get("name")
            if not job_url or not name:
                return {"name": name or "unknown", "builds": []}
            tree = f"builds[number,timestamp,result]{{0,{max_builds}}}"
            async with sem:
                try:
                    resp = await client.get(
                        f"{job_url.rstrip('/')}/api/json",
                        params={"tree": tree},
                        headers=headers,
                        auth=auth,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return {"name": name, "builds": data.get("builds", [])}
                except httpx.HTTPError:
                    return {"name": name, "builds": [], "error": True}

        job_results = await asyncio.gather(*[fetch_builds(job) for job in filtered_jobs])

    date_list = _daterange(days)
    date_keys = [d.isoformat() for d in date_list]
    date_set = set(date_keys)

    daily_totals = {key: 0 for key in date_keys}
    items: List[Dict[str, Any]] = []
    errors: List[str] = []

    min_date = date_list[0]

    for job in job_results:
        name = job.get("name")
        builds = job.get("builds", [])
        if job.get("error"):
            errors.append(name)
        job_daily = {key: 0 for key in date_keys}
        total = 0

        for build in builds:
            result = build.get("result")
            if success_only and result != "SUCCESS":
                continue

            ts = build.get("timestamp")
            if ts is None:
                continue
            build_date = date.fromtimestamp(ts / 1000)
            if build_date < min_date:
                continue
            key = build_date.isoformat()
            if key not in date_set:
                continue
            job_daily[key] += 1
            daily_totals[key] += 1
            total += 1

        items.append(
            {
                "name": name,
                "total": total,
                "daily": [{"date": key, "count": job_daily[key]} for key in date_keys],
            }
        )

    items.sort(key=lambda item: item["total"], reverse=True)

    response = {
        "generated_at": datetime.now().isoformat(),
        "days": days,
        "total": sum(daily_totals.values()),
        "daily": [{"date": key, "count": daily_totals[key]} for key in date_keys],
        "items": items,
        "filters": {
            "include": include,
            "exclude": exclude,
            "success_only": success_only,
            "max_builds": max_builds,
        },
        "errors": errors,
    }

    return response