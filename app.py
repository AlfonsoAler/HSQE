from datetime import datetime
from enum import Enum
from io import BytesIO
import sqlite3
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field


DB_PATH = "incidentes.db"

app = FastAPI(
    title="HSQE Incident API",
    description="API para registrar, consultar y exportar incidentes HSQE.",
    version="2.0.0",
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


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.on_event("startup")
def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                area TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                severidad TEXT NOT NULL,
                reportado_por TEXT NOT NULL,
                fecha_incidente TEXT NOT NULL,
                acciones_inmediatas TEXT,
                creado_en TEXT NOT NULL
            )
            """
        )
        conn.commit()


def row_to_incident(row: sqlite3.Row) -> Incident:
    return Incident(
        id=row["id"],
        area=row["area"],
        descripcion=row["descripcion"],
        severidad=row["severidad"],
        reportado_por=row["reportado_por"],
        fecha_incidente=datetime.fromisoformat(row["fecha_incidente"]),
        acciones_inmediatas=row["acciones_inmediatas"],
        creado_en=datetime.fromisoformat(row["creado_en"]),
    )


@app.get("/", tags=["salud"])
def healthcheck() -> dict:
    return {"status": "ok", "service": "HSQE Incident API", "storage": "sqlite"}


@app.get("/ui", response_class=HTMLResponse, tags=["frontend"])
def frontend() -> str:
    return open("templates/index.html", encoding="utf-8").read()


@app.post("/incidentes", response_model=Incident, status_code=201, tags=["incidentes"])
def crear_incidente(payload: IncidentCreate) -> Incident:
    now = datetime.utcnow().isoformat()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO incidentes (area, descripcion, severidad, reportado_por, fecha_incidente, acciones_inmediatas, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.area,
                payload.descripcion,
                payload.severidad.value,
                payload.reportado_por,
                payload.fecha_incidente.isoformat(),
                payload.acciones_inmediatas,
                now,
            ),
        )
        conn.commit()
        incidente_id = cursor.lastrowid

        row = conn.execute("SELECT * FROM incidentes WHERE id = ?", (incidente_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=500, detail="No fue posible crear el incidente")

    return row_to_incident(row)


@app.get("/incidentes", response_model=list[Incident], tags=["incidentes"])
def listar_incidentes(
    severidad: Optional[Severity] = None,
    area: Optional[str] = None,
) -> list[Incident]:
    query = "SELECT * FROM incidentes WHERE 1=1"
    params: list[str] = []

    if severidad is not None:
        query += " AND severidad = ?"
        params.append(severidad.value)

    if area is not None:
        query += " AND LOWER(area) LIKE ?"
        params.append(f"%{area.lower().strip()}%")

    query += " ORDER BY id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [row_to_incident(row) for row in rows]


@app.get("/incidentes/exportar.xlsx", tags=["incidentes"])
def exportar_incidentes_excel(
    severidad: Optional[Severity] = Query(default=None),
    area: Optional[str] = Query(default=None),
) -> StreamingResponse:
    incidentes = listar_incidentes(severidad=severidad, area=area)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Incidentes"

    sheet.append(
        [
            "ID",
            "Área",
            "Descripción",
            "Severidad",
            "Reportado por",
            "Fecha incidente",
            "Acciones inmediatas",
            "Creado en",
        ]
    )

    for incidente in incidentes:
        sheet.append(
            [
                incidente.id,
                incidente.area,
                incidente.descripcion,
                incidente.severidad.value,
                incidente.reportado_por,
                incidente.fecha_incidente.isoformat(),
                incidente.acciones_inmediatas or "",
                incidente.creado_en.isoformat(),
            ]
        )

    file_stream = BytesIO()
    workbook.save(file_stream)
    file_stream.seek(0)

    filename = f"incidentes_hsqe_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return StreamingResponse(
        file_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/incidentes/{incidente_id}", response_model=Incident, tags=["incidentes"])
def obtener_incidente(incidente_id: int) -> Incident:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM incidentes WHERE id = ?", (incidente_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")

    return row_to_incident(row)


@app.patch("/incidentes/{incidente_id}", response_model=Incident, tags=["incidentes"])
def actualizar_incidente(incidente_id: int, payload: IncidentUpdate) -> Incident:
    nullable_fields = {"acciones_inmediatas"}
    null_disallowed_fields = [
        field_name
        for field_name in payload.model_fields_set
        if field_name not in nullable_fields and getattr(payload, field_name) is None
    ]
    if null_disallowed_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Los campos {', '.join(null_disallowed_fields)} no permiten null.",
        )

    update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not update_data:
        return obtener_incidente(incidente_id)

    fields = []
    values = []

    for key, value in update_data.items():
        if key == "severidad":
            value = value.value
        if isinstance(value, datetime):
            value = value.isoformat()
        fields.append(f"{key} = ?")
        values.append(value)

    values.append(incidente_id)

    with get_connection() as conn:
        result = conn.execute(
            f"UPDATE incidentes SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Incidente no encontrado")

        row = conn.execute("SELECT * FROM incidentes WHERE id = ?", (incidente_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")

    return row_to_incident(row)


@app.delete("/incidentes/{incidente_id}", status_code=204, tags=["incidentes"])
def eliminar_incidente(incidente_id: int) -> None:
    with get_connection() as conn:
        result = conn.execute("DELETE FROM incidentes WHERE id = ?", (incidente_id,))
        conn.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
