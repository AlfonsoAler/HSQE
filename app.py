from datetime import datetime
from enum import Enum
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(
    title="HSQE Incident API",
    description="API para registrar y consultar incidentes HSQE.",
    version="1.0.0",
)


class Severity(str, Enum):
    baja = "baja"
    media = "media"
    alta = "alta"
    critica = "critica"


class IncidentBase(BaseModel):
    area: str = Field(..., min_length=2, max_length=120, description="Área donde ocurrió")
    descripcion: str = Field(..., min_length=5, max_length=1000)
    severidad: Severity
    reportado_por: str = Field(..., min_length=2, max_length=120)
    fecha_incidente: datetime = Field(default_factory=datetime.utcnow)
    acciones_inmediatas: Optional[str] = Field(default=None, max_length=1000)


class IncidentCreate(IncidentBase):
    pass


class Incident(IncidentBase):
    id: int
    creado_en: datetime


class IncidentUpdate(BaseModel):
    area: Optional[str] = Field(default=None, min_length=2, max_length=120)
    descripcion: Optional[str] = Field(default=None, min_length=5, max_length=1000)
    severidad: Optional[Severity] = None
    reportado_por: Optional[str] = Field(default=None, min_length=2, max_length=120)
    fecha_incidente: Optional[datetime] = None
    acciones_inmediatas: Optional[str] = Field(default=None, max_length=1000)


incidentes: List[Incident] = []
next_id = 1


@app.get("/", tags=["salud"])
def healthcheck() -> dict:
    return {"status": "ok", "service": "HSQE Incident API"}


@app.post("/incidentes", response_model=Incident, status_code=201, tags=["incidentes"])
def crear_incidente(payload: IncidentCreate) -> Incident:
    global next_id

    incidente = Incident(id=next_id, creado_en=datetime.utcnow(), **payload.model_dump())
    incidentes.append(incidente)
    next_id += 1
    return incidente


@app.get("/incidentes", response_model=List[Incident], tags=["incidentes"])
def listar_incidentes(
    severidad: Optional[Severity] = None,
    area: Optional[str] = None,
) -> List[Incident]:
    resultados = incidentes

    if severidad is not None:
        resultados = [i for i in resultados if i.severidad == severidad]

    if area is not None:
        area_lower = area.lower().strip()
        resultados = [i for i in resultados if area_lower in i.area.lower()]

    return resultados


@app.get("/incidentes/{incidente_id}", response_model=Incident, tags=["incidentes"])
def obtener_incidente(incidente_id: int) -> Incident:
    for incidente in incidentes:
        if incidente.id == incidente_id:
            return incidente

    raise HTTPException(status_code=404, detail="Incidente no encontrado")


@app.patch("/incidentes/{incidente_id}", response_model=Incident, tags=["incidentes"])
def actualizar_incidente(incidente_id: int, payload: IncidentUpdate) -> Incident:
    for index, incidente in enumerate(incidentes):
        if incidente.id == incidente_id:
            update_data = payload.model_dump(exclude_unset=True)
            incidente_actualizado = incidente.model_copy(update=update_data)
            incidentes[index] = incidente_actualizado
            return incidente_actualizado

    raise HTTPException(status_code=404, detail="Incidente no encontrado")


@app.delete("/incidentes/{incidente_id}", status_code=204, tags=["incidentes"])
def eliminar_incidente(incidente_id: int) -> None:
    for index, incidente in enumerate(incidentes):
        if incidente.id == incidente_id:
            incidentes.pop(index)
            return

    raise HTTPException(status_code=404, detail="Incidente no encontrado")
