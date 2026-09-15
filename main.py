"""
main.py — Carbon-Aware API Gateway v3.0
COMP 4206 Cloud Computing — Phase 1 Demo
Konya Food and Agriculture University

Çalıştırma:
    pip install -r requirements.txt
    python main.py

Dashboard : http://localhost:8000/dashboard
API Docs  : http://localhost:8000/docs
"""

from contextlib import asynccontextmanager
import logging

from config import Region, HOST, PORT, ENTSOE_API_KEY
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from config import ROOT
from pydantic import BaseModel
from typing import Literal, Any, Dict

from gateway.database import init, log, get_logs, get_stats
from scheduler.engine import carbon_aware, round_robin, latency_only
from carbon_api.service import get_current
from forecasting.arima import get_forecast, get_all_forecasts
from optimizer.pareto import optimize
from openwhisk.cluster import cluster_status


@asynccontextmanager
async def lifespan(app):
    init()
    logging.getLogger(__name__).info("gateway_started")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Carbon-Aware API Gateway",
    version="3.0.0",
    description="Energy-Aware Serverless Function Placement — Phase 1 Demo | COMP 4206",
)

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class RouteRequest(BaseModel):
    action: str = "default_action"
    function_type: Literal["standard", "latency_sensitive", "delay_tolerant"] = (
        "standard"
    )
    scheduler: Literal["carbon_aware", "round_robin", "latency_only"] = "carbon_aware"
    opt_method: Literal["weighted_sum", "pareto", "epsilon"] = "weighted_sum"
    data: Dict[str, Any] = {}


@app.post("/route", summary="Route a function invocation")
def route(req: RouteRequest):
    if req.scheduler == "carbon_aware":
        result = carbon_aware(req.action, req.data, req.function_type, req.opt_method)
    elif req.scheduler == "round_robin":
        result = round_robin(req.action, req.data, req.function_type)
    else:
        result = latency_only(req.action, req.data, req.function_type)
    result["action"] = req.action
    log(result)
    return result


@app.get("/carbon")
def carbon():
    return get_current()


@app.get("/forecast/{region}")
def forecast(region: Region, steps: int = Query(6, ge=1, le=24)):
    return get_forecast(region, steps)


@app.get("/forecast")
def forecast_all(steps: int = Query(6, ge=1, le=24)):
    return get_all_forecasts(steps=steps)


@app.get("/pareto")
def pareto():
    snap = get_current()
    return {
        "snapshot_hour": snap["hour"],
        "weighted_sum": optimize(snap, "weighted_sum"),
        "pareto": optimize(snap, "pareto"),
        "epsilon": optimize(snap, "epsilon"),
        "pareto_front": optimize(snap, "pareto").get("pareto_front", []),
    }


@app.get("/clusters")
def clusters():
    return cluster_status()


@app.get("/logs")
def logs(limit: int = Query(60, ge=1, le=200)):
    return get_logs(limit)


@app.get("/stats")
def stats():
    return get_stats()


@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    return HTMLResponse((ROOT / "dashboard.html").read_text(encoding="utf-8"))


@app.get("/forecast/prophet/{region}")
def get_prophet_forecast_endpoint(region: Region, steps: int = Query(6, ge=1, le=24)):
    from forecasting.prophet_model import get_prophet_forecast

    return get_prophet_forecast(region, steps)


@app.get("/entsoe/status")
def entsoe_status():
    """ENTSO-E token durumu ve 4 bolge ozeti."""
    token = ENTSOE_API_KEY
    from carbon_api.entsoe import get_all_regions

    if not token:
        return {
            "active": False,
            "message": "ENTSOE_API_KEY eksik — .env dosyasina ekleyin",
            "signup": "https://transparency.entsoe.eu/",
        }
    results = get_all_regions()
    return {
        "active": True,
        "regions": {
            r: {
                "carbon_intensity": d["carbon_intensity"],
                "renewable_pct": d["renewable_pct"],
                "source": d["source"],
            }
            for r, d in results.items()
        },
    }


@app.get("/entsoe/{region}")
def entsoe_detail(region: Region):
    """ENTSO-E uretim tipi detayi (token gerekli)."""
    from carbon_api.entsoe import get_carbon_intensity

    return get_carbon_intensity(region)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
