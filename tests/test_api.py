import os

import pytest
from fastapi.testclient import TestClient

os.environ.pop("ANTHROPIC_API_KEY", None)  # los tests siempre en modo demo

from app import guards  # noqa: E402
from app.main import OUTBOX, app  # noqa: E402
from app.samples import SAMPLES  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    guards.reset()
    OUTBOX.clear()


def _payload(sample):
    return {k: sample[k] for k in ("id", "remitente", "asunto", "cuerpo")}


def test_health_demo():
    assert client.get("/api/health").json()["modo"] == "demo"


def test_samples_do_not_leak_expected_labels():
    data = client.get("/api/samples").json()
    assert len(data) == len(SAMPLES)
    assert all("esperado" not in s for s in data)


def test_triage_returns_structured_result():
    r = client.post("/api/triage", json={"emails": [_payload(SAMPLES[1])]})
    assert r.status_code == 200
    t = r.json()[0]["triage"]
    assert t["categoria"] == "incidencia" and t["prioridad"] == "alta"
    assert t["borrador"]["cuerpo"]


def test_extracts_key_data():
    t = client.post("/api/triage", json={"emails": [_payload(SAMPLES[2])]}).json()[0]["triage"]
    assert "1.284,50" in t["datos"]["importe"]
    assert t["datos"]["referencia"] == "F-2026-0412"


def test_prompt_injection_is_flagged_not_obeyed():
    t = client.post("/api/triage", json={"emails": [_payload(SAMPLES[7])]}).json()[0]["triage"]
    assert t["prioridad"] == "baja"
    assert t["alerta_seguridad"]
    assert t["requiere_revision"] is True


def test_validation_limits():
    big = {"remitente": "a@b.com", "asunto": "x", "cuerpo": "x" * 6001}
    assert client.post("/api/triage", json={"emails": [big]}).status_code == 422
    many = {"remitente": "a@b.com", "asunto": "x", "cuerpo": "hola"}
    assert client.post("/api/triage", json={"emails": [many] * 21}).status_code == 422


def test_rate_limit():
    body = {"emails": [_payload(SAMPLES[0])]}
    codes = [client.post("/api/triage", json=body).status_code for _ in range(guards.MAX_REQUESTS_PER_MINUTE + 1)]
    assert codes[-1] == 429


def test_outbox_only_receives_approved_and_never_sends():
    assert client.get("/api/outbox").json() == []
    r = client.post("/api/outbox", json={"email_id": "s01", "destinatario": "a@b.com", "asunto": "Re: x", "cuerpo": "Hola"})
    assert r.status_code == 201 and r.json()["enviado_realmente"] is False
    assert len(client.get("/api/outbox").json()) == 1


def test_demo_accuracy_floor():
    from app.demo import triage_demo
    from app.schemas import EmailIn

    hits = 0
    for s in SAMPLES:
        t = triage_demo(EmailIn(**_payload(s)), s["id"]).triage
        hits += t.categoria == s["esperado"]["categoria"] and t.prioridad == s["esperado"]["prioridad"]
    assert hits / len(SAMPLES) >= 0.8


def test_live_path_parses_forced_tool_output(monkeypatch):
    """Simula la respuesta de Claude (tool_use) para probar la ruta live sin gastar tokens."""
    from types import SimpleNamespace

    from app import llm

    fake_input = {
        "categoria": "factura", "prioridad": "media", "motivo_prioridad": "Vence en dos semanas.",
        "resumen": "Envían una factura.",
        "datos": {"nombre_contacto": None, "empresa": "Papelería Sánchez", "importe": "1.284,50 €",
                  "fecha_limite": "30/11/2026", "referencia": "F-2026-0412", "producto_o_servicio": None},
        "acciones_sugeridas": ["Pasar a contabilidad"],
        "borrador": {"asunto": "Re: Factura", "cuerpo": "Hola,\n\nRecibida.\n\nUn saludo"},
        "confianza": 0.93, "requiere_revision": False, "alerta_seguridad": None,
    }
    calls = {}

    class FakeMessages:
        async def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", input=fake_input)],
                usage=SimpleNamespace(input_tokens=700, output_tokens=210),
            )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_client", SimpleNamespace(messages=FakeMessages()))
    r = client.post("/api/triage", json={"emails": [_payload(SAMPLES[2])]}).json()[0]
    assert r["modo"] == "live" and r["triage"]["categoria"] == "factura"
    assert r["tokens_entrada"] == 700
    assert calls["tool_choice"] == {"type": "tool", "name": "registrar_triaje"}  # salida estructurada forzada
    assert "<email>" in calls["messages"][0]["content"]  # el email va delimitado como dato no fiable


def test_live_failure_does_not_break_batch(monkeypatch):
    from types import SimpleNamespace

    from app import llm

    class Boom:
        async def create(self, **kwargs):
            raise RuntimeError("api caída")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_client", SimpleNamespace(messages=Boom()))
    res = client.post("/api/triage", json={"emails": [_payload(SAMPLES[0]), _payload(SAMPLES[1])]})
    assert res.status_code == 200
    assert all(x["triage"] is None and x["error"] for x in res.json())
