# HSQE

Aplicación **FastAPI** para registrar incidentes de Seguridad, Salud, Calidad y Medio Ambiente (HSQE).

## Requisitos

- Python 3.10+
- pip

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar

```bash
uvicorn app:app --reload
```

La API quedará disponible en:

- `http://127.0.0.1:8000`
- Documentación Swagger: `http://127.0.0.1:8000/docs`

## Endpoints principales

- `POST /incidentes`: registrar incidente
- `GET /incidentes`: listar incidentes (filtro opcional por `severidad` y `area`)
- `GET /incidentes/{incidente_id}`: obtener detalle
- `PATCH /incidentes/{incidente_id}`: actualizar parcialmente
- `DELETE /incidentes/{incidente_id}`: eliminar incidente

## Ejemplo de payload

```json
{
  "area": "Planta Norte",
  "descripcion": "Derrame menor de químico en zona de carga",
  "severidad": "media",
  "reportado_por": "María López",
  "fecha_incidente": "2026-05-15T08:30:00Z",
  "acciones_inmediatas": "Se aisló el área y se aplicó kit de contención"
}
```
