from datetime import datetime, timedelta
from enum import Enum
from io import BytesIO
import hashlib
import hmac
import secrets
import sqlite3
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field


DB_PATH = "incidentes.db"
SESSION_MINUTES = 60 * 8

app = FastAPI(
    title="HSQE Incident API",
    description="API para registrar, consultar y exportar incidentes HSQE.",
    version="3.0.0",
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


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


class UserOut(BaseModel):
    id: int
    username: str


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                creado_en TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sesiones (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expira_en TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES usuarios(id)
            )
            """
        )
        existing = conn.execute("SELECT id FROM usuarios WHERE username = ?", ("admin",)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO usuarios (username, password_hash, creado_en) VALUES (?, ?, ?)",
                ("admin", hash_password("admin123"), datetime.utcnow().isoformat()),
            )
        conn.commit()


def get_current_user(authorization: Optional[str] = Header(default=None)) -> UserOut:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")

    token = authorization.removeprefix("Bearer ").strip()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, s.expira_en
            FROM sesiones s
            JOIN usuarios u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="Sesión inválida")

    if datetime.fromisoformat(row["expira_en"]) < datetime.utcnow():
        with get_connection() as conn:
            conn.execute("DELETE FROM sesiones WHERE token = ?", (token,))
            conn.commit()
        raise HTTPException(status_code=401, detail="Sesión expirada")

    return UserOut(id=row["id"], username=row["username"])


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
    return {"status": "ok", "service": "HSQE Incident API", "storage": "sqlite", "auth": "token"}


@app.get("/ui", response_class=HTMLResponse, tags=["frontend"])
def frontend() -> str:
    return open("templates/index.html", encoding="utf-8").read()


@app.post("/auth/login", response_model=LoginResponse, tags=["auth"])
def login(payload: LoginRequest) -> LoginResponse:
    with get_connection() as conn:
        user = conn.execute("SELECT id, password_hash FROM usuarios WHERE username = ?", (payload.username,)).fetchone()

    if user is None or not hmac.compare_digest(user["password_hash"], hash_password(payload.password)):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(minutes=SESSION_MINUTES)).isoformat()
    with get_connection() as conn:
        conn.execute("INSERT INTO sesiones (token, user_id, expira_en) VALUES (?, ?, ?)", (token, user["id"], expires_at))
        conn.commit()

    return LoginResponse(token=token, expires_at=expires_at)


@app.get("/auth/me", response_model=UserOut, tags=["auth"])
def auth_me(current_user: UserOut = Depends(get_current_user)) -> UserOut:
    return current_user


@app.post("/incidentes", response_model=Incident, status_code=201, tags=["incidentes"])
def crear_incidente(payload: IncidentCreate, _: UserOut = Depends(get_current_user)) -> Incident:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO incidentes (area, descripcion, severidad, reportado_por, fecha_incidente, acciones_inmediatas, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (payload.area, payload.descripcion, payload.severidad.value, payload.reportado_por, payload.fecha_incidente.isoformat(), payload.acciones_inmediatas, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM incidentes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="No fue posible crear el incidente")
    return row_to_incident(row)


@app.get("/incidentes", response_model=list[Incident], tags=["incidentes"])
def listar_incidentes(severidad: Optional[Severity] = None, area: Optional[str] = None, _: UserOut = Depends(get_current_user)) -> list[Incident]:
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
def exportar_incidentes_excel(severidad: Optional[Severity] = Query(default=None), area: Optional[str] = Query(default=None), _: UserOut = Depends(get_current_user)) -> StreamingResponse:
    incidentes = listar_incidentes(severidad=severidad, area=area, _=_)  # type: ignore[arg-type]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Incidentes"
    sheet.append(["ID", "Área", "Descripción", "Severidad", "Reportado por", "Fecha incidente", "Acciones inmediatas", "Creado en"])
    for incidente in incidentes:
        sheet.append([incidente.id, incidente.area, incidente.descripcion, incidente.severidad.value, incidente.reportado_por, incidente.fecha_incidente.isoformat(), incidente.acciones_inmediatas or "", incidente.creado_en.isoformat()])
    file_stream = BytesIO()
    workbook.save(file_stream)
    file_stream.seek(0)
    filename = f"incidentes_hsqe_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(file_stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.get("/incidentes/{incidente_id}", response_model=Incident, tags=["incidentes"])
def obtener_incidente(incidente_id: int, _: UserOut = Depends(get_current_user)) -> Incident:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM incidentes WHERE id = ?", (incidente_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
    return row_to_incident(row)


@app.patch("/incidentes/{incidente_id}", response_model=Incident, tags=["incidentes"])
def actualizar_incidente(incidente_id: int, payload: IncidentUpdate, _: UserOut = Depends(get_current_user)) -> Incident:
    nullable_fields = {"acciones_inmediatas"}
    null_disallowed_fields = [field_name for field_name in payload.model_fields_set if field_name not in nullable_fields and getattr(payload, field_name) is None]
    if null_disallowed_fields:
        raise HTTPException(status_code=422, detail=f"Los campos {', '.join(null_disallowed_fields)} no permiten null.")
    update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not update_data:
        return obtener_incidente(incidente_id, _)
    fields, values = [], []
    for key, value in update_data.items():
        if key == "severidad":
            value = value.value
        if isinstance(value, datetime):
            value = value.isoformat()
        fields.append(f"{key} = ?")
        values.append(value)
    values.append(incidente_id)
    with get_connection() as conn:
        result = conn.execute(f"UPDATE incidentes SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Incidente no encontrado")
        row = conn.execute("SELECT * FROM incidentes WHERE id = ?", (incidente_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
    return row_to_incident(row)


@app.delete("/incidentes/{incidente_id}", status_code=204, tags=["incidentes"])
def eliminar_incidente(incidente_id: int, _: UserOut = Depends(get_current_user)) -> None:
    with get_connection() as conn:
        result = conn.execute("DELETE FROM incidentes WHERE id = ?", (incidente_id,))
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
