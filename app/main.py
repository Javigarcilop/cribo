import asyncio
import logging
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from . import guards, llm  # noqa: E402  (después de cargar .env)
from .demo import triage_demo  # noqa: E402
from .samples import SAMPLES  # noqa: E402
from .schemas import OutboxIn, TriageRequest, TriageResult  # noqa: E402

log = logging.getLogger("bandeja")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Cribo", version="1.0.0")

# "Bandeja de salida" simulada: aquí solo llegan borradores APROBADOS por una persona.
# No hay ninguna integración de envío real a propósito.
OUTBOX: list[dict] = []

_sem = asyncio.Semaphore(4)


@app.get("/api/health")
def health():
    return {"modo": "live" if llm.live_available() else "demo", "modelo": llm.MODEL if llm.live_available() else None}


@app.get("/api/samples")
def samples():
    return [{k: v for k, v in s.items() if k != "esperado"} for s in SAMPLES]


async def _triage_one(email, email_id: str, live: bool) -> TriageResult:
    if not live:
        return triage_demo(email, email_id)
    async with _sem:
        try:
            return await llm.triage_live(email, email_id)
        except Exception as exc:  # el fallo de un email no tumba el lote
            log.warning("fallo triaje %s: %s", email_id, type(exc).__name__)
            return TriageResult(id=email_id, modo="live", error="No se pudo analizar este email. Inténtalo de nuevo.")


@app.post("/api/triage", response_model=list[TriageResult])
async def triage(req: TriageRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    if not guards.allow_request(ip):
        raise HTTPException(429, "Demasiadas peticiones. Espera un minuto.")
    live = llm.live_available()
    if live and not guards.reserve_llm_calls(len(req.emails)):
        raise HTTPException(429, "Límite de uso del modelo alcanzado. Vuelve a intentarlo más tarde.")
    ids = [e.id or f"e{i}-{uuid.uuid4().hex[:6]}" for i, e in enumerate(req.emails)]
    return await asyncio.gather(*[_triage_one(e, i, live) for e, i in zip(req.emails, ids)])


@app.post("/api/outbox", status_code=201)
def approve(item: OutboxIn):
    """Puerta de aprobación humana: solo lo que una persona aprueba entra aquí."""
    OUTBOX.append(item.model_dump())
    return {"aprobados": len(OUTBOX), "enviado_realmente": False}


@app.get("/api/outbox")
def outbox():
    return OUTBOX


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
