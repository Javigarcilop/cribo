"""Modo demo: triaje con reglas simples, sin API key ni coste.

Sirve para probar la interfaz, para los tests y para que cualquiera pueda
arrancar el proyecto sin cuenta. No pretende igualar a Claude: en la evaluación
se compara el modo demo contra el modo live.
"""
import re
import time
from email.utils import parseaddr

from .schemas import Borrador, DatosClave, EmailIn, Triage, TriageResult

INJECTION = re.compile(
    r"ignora (todas )?(tus|las) instrucciones|ignore (all )?(previous|prior) instructions|"
    r"olvida (todo|lo anterior)|system prompt|prompt del sistema|act[uú]a como|"
    r"clasifica (este|esto|el) (correo|email|mensaje) como",
    re.I,
)

KEYWORDS = {
    "factura": r"factura(?!r)|vencimiento|impago|recibo|abono|iban|reclamaci[oó]n de pago|pago pendiente",
    "incidencia": r"error|no funciona|no podemos|no puedo|ca[ií]d[ao]|fallo|incidencia|roto|da[ñn]ado|devoluci[oó]n|bloquead|pixelad|parad[oa]s",
    "presupuesto": r"presupuesto|cotizaci[oó]n|propuesta econ[oó]mica|precio|tarifa|cu[aá]nto cuesta",
    "comercial": r"colaboraci[oó]n|partnership|posicionamiento|seo|oferta especial|descuento|os ofrecemos|le ofrecemos|reuni[oó]n|alianza",
}
URGENTES = r"urgente|hoy mismo|ma[ñn]ana|parad[oa]s|sin servicio|reclamaci[oó]n|recargo|impago|inaceptable|cuanto antes"
RELAJADOS = r"sin prisa|no es urgente|cuando pod[aá]is|cuando puedas|no hay urgencia"
PLAZO = r"antes del|hasta el|para el (lunes|martes|mi[eé]rcoles|jueves|viernes)"
GRANDE = r"contrato marco|colaboraci[oó]n anual|volumen|\b\d{2,} (licencias|unidades|usuarios)"

IMPORTE = re.compile(r"\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?\s?(?:€|euros|EUR)|\d+(?:,\d{1,2})?\s?(?:€|euros|EUR)", re.I)
FECHA = re.compile(
    r"\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2} de (?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)|"
    r"(?:este |el )?(?:lunes|martes|mi[eé]rcoles|jueves|viernes)",
    re.I,
)
REFERENCIA = re.compile(r"\b(?:[A-Z]{1,4}-\d{2,4}-\d{2,6}|[A-Z]{2,4}-\d{3,8}|n[ºo°] ?\d{3,8})\b")


def _detect_category(text: str) -> str:
    scores = {c: len(re.findall(p, text, re.I)) for c, p in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "otro"


def _priority(text: str, categoria: str) -> tuple[str, str]:
    if categoria == "otro":
        return "baja", "No requiere acción: aviso automático o mensaje sin petición clara."
    score = {"incidencia": 1, "factura": 1, "presupuesto": 0, "comercial": -1, "otro": -2}[categoria]
    reasons: list[str] = []
    if re.search(URGENTES, text, re.I) and not re.search(RELAJADOS, text, re.I):
        score += 2
        reasons.append("lenguaje urgente o de reclamación")
    if re.search(PLAZO, text, re.I):
        score += 1
        reasons.append("hay un plazo")
    if re.search(GRANDE, text, re.I):
        score += 2
        reasons.append("volumen o relación de más peso")
    if categoria == "incidencia" and re.search(r"roto|da[ñn]ado|devoluci[oó]n", text, re.I):
        score += 1
        reasons.append("producto dañado o devolución")
    if re.search(RELAJADOS, text, re.I):
        score -= 2
        reasons.append("el remitente indica que no hay prisa")
    level = "alta" if score >= 3 else "media" if score >= 1 else "baja"
    return level, ("; ".join(reasons) or f"categoría {categoria} sin señales de urgencia").capitalize() + "."


def _first(regex: re.Pattern, text: str) -> str | None:
    m = regex.search(text)
    return m.group(0).strip() if m else None


def _draft(categoria: str, nombre: str | None, asunto: str, prioridad: str) -> Borrador:
    saludo = f"Hola {nombre}," if nombre else "Hola,"
    cuerpos = {
        "presupuesto": "Gracias por contactar con nosotros. Hemos recibido tu petición y te enviaremos el presupuesto antes de [indicar fecha]. Si necesitas ajustar alguna cantidad o requisito, dínoslo.",
        "incidencia": "Lamentamos las molestias. Ya hemos abierto la incidencia y la estamos revisando. Te daremos una actualización antes de [indicar hora]. Si puedes, envíanos una captura o el detalle del error.",
        "factura": "Gracias por tu mensaje. Hemos revisado el asunto de la factura y te confirmaremos el estado a lo largo de [indicar fecha]. Si necesitas una copia, te la enviamos en cuanto lo indiques.",
        "comercial": "Gracias por escribirnos. Por ahora no tenemos previsto cambiar de proveedor, pero guardamos tu contacto. Si hay una propuesta concreta, envíanosla por escrito.",
        "otro": "Gracias por tu mensaje. Lo hemos recibido y lo revisaremos en cuanto sea posible.",
    }
    return Borrador(
        asunto=f"Re: {asunto}" if asunto else "Re: tu mensaje",
        cuerpo=f"{saludo}\n\n{cuerpos[categoria]}\n\nUn saludo,\n[Nombre] · Mi Empresa",
    )


def triage_demo(email: EmailIn, email_id: str) -> TriageResult:
    start = time.perf_counter()
    text = f"{email.asunto}\n{email.cuerpo}"
    nombre_header, direccion = parseaddr(email.remitente)
    nombre = nombre_header.split()[0] if nombre_header else None
    dominio = direccion.split("@")[-1].split(".")[0].capitalize() if "@" in direccion else None

    alerta = None
    if INJECTION.search(text):
        categoria, prioridad = "otro", "baja"
        motivo = "El texto intenta dar órdenes al asistente; se trata como contenido sospechoso."
        alerta = "El email contiene instrucciones dirigidas a la IA (posible prompt injection). Se ha ignorado su contenido."
    else:
        categoria = _detect_category(text)
        prioridad, motivo = _priority(text, categoria)

    datos = DatosClave(
        nombre_contacto=nombre_header or None,
        empresa=dominio if dominio and dominio.lower() not in {"gmail", "hotmail", "outlook", "yahoo"} else None,
        importe=_first(IMPORTE, text),
        fecha_limite=_first(FECHA, text),
        referencia=_first(REFERENCIA, text),
    )
    acciones = {
        "presupuesto": ["Preparar presupuesto", "Confirmar cantidades con el cliente"],
        "incidencia": ["Abrir ticket interno", "Avisar al responsable técnico"],
        "factura": ["Revisar la factura en contabilidad", "Confirmar estado de pago"],
        "comercial": ["Archivar o valorar la propuesta"],
        "otro": ["Revisar manualmente"],
    }[categoria]
    resumen = re.sub(r"\s+", " ", email.cuerpo).strip()
    resumen = resumen[:160] + ("…" if len(resumen) > 160 else "")
    return TriageResult(
        id=email_id,
        modo="demo",
        triage=Triage(
            categoria=categoria,
            prioridad=prioridad,
            motivo_prioridad=motivo,
            resumen=resumen,
            datos=datos,
            acciones_sugeridas=acciones,
            borrador=_draft(categoria, nombre, email.asunto, prioridad),
            confianza=0.55,
            requiere_revision=bool(alerta) or prioridad == "alta",
            alerta_seguridad=alerta,
        ),
        latencia_ms=int((time.perf_counter() - start) * 1000),
    )
