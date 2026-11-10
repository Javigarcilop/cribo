"""Evaluación: compara el triaje con las etiquetas esperadas de app/samples.py.

Uso:
  python -m eval.run_eval          # usa Claude si hay ANTHROPIC_API_KEY, si no el modo demo
Muestra acierto de categoría y prioridad, latencia media y tokens por email.
"""
import asyncio
import statistics

from dotenv import load_dotenv

load_dotenv()

from app import llm  # noqa: E402
from app.demo import triage_demo  # noqa: E402
from app.samples import SAMPLES  # noqa: E402
from app.schemas import EmailIn  # noqa: E402


async def main() -> None:
    live = llm.live_available()
    print(f"Modo: {'live (' + llm.MODEL + ')' if live else 'demo (reglas)'}\n")
    ok_cat = ok_pri = 0
    latencias: list[int] = []
    tokens = 0
    for s in SAMPLES:
        email = EmailIn(id=s["id"], remitente=s["remitente"], asunto=s["asunto"], cuerpo=s["cuerpo"])
        res = await llm.triage_live(email, s["id"]) if live else triage_demo(email, s["id"])
        t, exp = res.triage, s["esperado"]
        c_ok, p_ok = t.categoria == exp["categoria"], t.prioridad == exp["prioridad"]
        ok_cat += c_ok
        ok_pri += p_ok
        latencias.append(res.latencia_ms)
        tokens += res.tokens_entrada + res.tokens_salida
        marca = lambda b: "ok " if b else "MAL"
        print(f"{s['id']}  cat {marca(c_ok)} ({t.categoria:<11}) pri {marca(p_ok)} ({t.prioridad:<5})  {s['asunto'][:45]}")
    n = len(SAMPLES)
    print(f"\nAcierto categoría: {ok_cat}/{n} ({ok_cat / n:.0%})")
    print(f"Acierto prioridad: {ok_pri}/{n} ({ok_pri / n:.0%})")
    print(f"Latencia media: {statistics.mean(latencias):.0f} ms")
    if live:
        print(f"Tokens medios por email: {tokens / n:.0f}")


if __name__ == "__main__":
    asyncio.run(main())
