from typing import Literal

from pydantic import BaseModel, Field

Categoria = Literal["presupuesto", "incidencia", "factura", "comercial", "otro"]
Prioridad = Literal["alta", "media", "baja"]


class EmailIn(BaseModel):
    id: str | None = None
    remitente: str = Field(min_length=1, max_length=200)
    asunto: str = Field(default="", max_length=300)
    cuerpo: str = Field(min_length=1, max_length=6000)


class TriageRequest(BaseModel):
    emails: list[EmailIn] = Field(min_length=1, max_length=20)


class DatosClave(BaseModel):
    nombre_contacto: str | None = None
    empresa: str | None = None
    importe: str | None = None
    fecha_limite: str | None = None
    referencia: str | None = None
    producto_o_servicio: str | None = None


class Borrador(BaseModel):
    asunto: str
    cuerpo: str


class Triage(BaseModel):
    categoria: Categoria
    prioridad: Prioridad
    motivo_prioridad: str
    resumen: str
    datos: DatosClave = DatosClave()
    acciones_sugeridas: list[str] = []
    borrador: Borrador
    confianza: float = Field(ge=0, le=1)
    requiere_revision: bool
    alerta_seguridad: str | None = None


class TriageResult(BaseModel):
    id: str
    modo: Literal["live", "demo"]
    triage: Triage | None = None
    error: str | None = None
    latencia_ms: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0


class OutboxIn(BaseModel):
    email_id: str
    destinatario: str = Field(max_length=200)
    asunto: str = Field(max_length=300)
    cuerpo: str = Field(max_length=8000)
