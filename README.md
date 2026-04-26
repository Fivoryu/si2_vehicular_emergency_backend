# Backend - Asistencia Vehicular

Servidor API REST construido con **FastAPI** para gestionar emergencias vehiculares, talleres y usuarios.

## 🏗️ Arquitectura

```
backend/
├── app/
│   ├── main.py              # Punto de entrada FastAPI
│   ├── api/
│   │   ├── deps.py          # Dependencias
│   │   └── v1/
│   │       ├── router.py    # Enrutamiento v1
│   │       └── endpoints/   # Controladores (auth, clients, emergencies)
│   ├── core/
│   │   ├── config.py        # Configuración
│   │   └── security.py      # JWT y seguridad
│   ├── db/
│   │   ├── session.py       # Sesión de BD
│   │   ├── base.py          # Modelos base
│   │   └── seed.py          # Datos de prueba
│   ├── models/              # Modelos SQLAlchemy
│   ├── schemas/             # Esquemas Pydantic
│   └── services/            # Lógica de negocio
├── docker/
│   └── Dockerfile           # Imagen Docker
├── requirements.txt         # Dependencias Python
├── .dockerignore
└── README.md               # Este archivo
```

## 🚀 Inicio Rápido

### Local (con Python)

```bash
# 1. Crear entorno virtual
python -m venv .venv

# 2. Activar (Windows)
.venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ejecutar servidor
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Con Docker

```bash
docker build -f docker/Dockerfile -t asistencia-backend:latest .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://postgres:password@host.docker.internal:5432/asistencia_vehicular \
  asistencia-backend:latest
```

### Con Docker Compose

```bash
cd ..
docker-compose up backend postgres localstack
```

## 📋 Dependencias

| Paquete | Versión | Propósito |
|---------|---------|----------|
| fastapi | 0.115.12 | Framework REST API |
| uvicorn | 0.34.2 | Servidor ASGI |
| sqlalchemy | 2.0.40 | ORM |
| asyncpg | 0.30.0 | Driver PostgreSQL async |
| pydantic-settings | 2.8.1 | Gestión config |
| boto3 | 1.38.3 | AWS SDK |
| python-multipart | 0.0.20 | Multipart form |
| email-validator | 2.2.0 | Validación email |

## 🔐 Variables de Entorno

```bash
DATABASE_URL=postgresql://postgres:password@localhost:5432/asistencia_vehicular
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_REGION=us-east-1
AWS_S3_BUCKET_NAME=asistencia-vehicular-bucket
AWS_ENDPOINT_URL=http://localstack:4566
DEBUG=True
HOST=0.0.0.0
PORT=8000
```

## 📡 Endpoints Principales

```
POST   /api/v1/auth/login              # Iniciar sesión
POST   /api/v1/auth/register/client    # Registrar cliente
GET    /api/v1/clients/{id}/vehicles   # Listar vehículos
POST   /api/v1/emergencies             # Reportar emergencia
GET    /api/v1/emergencies/{id}        # Obtener emergencia
POST   /api/v1/emergencies/{id}/evidences # Adjuntar evidencia
POST   /api/v1/emergencies/{id}/payments # Registrar pago del servicio
```

## 📦 Deployment en AWS

### ECR + ECS

```bash
# 1. Crear repositorio ECR
aws ecr create-repository --repository-name asistencia-backend

# 2. Build y push
docker tag asistencia-backend:latest YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/asistencia-backend:latest
docker push YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/asistencia-backend:latest

# 3. Crear Task Definition y ECS Service
# Ver docs/aws-deployment.md
```

### RDS PostgreSQL

```bash
aws rds create-db-instance \
  --db-instance-identifier asistencia-db \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --master-username postgres \
  --allocated-storage 20
```

## 📚 Documentación Adicional

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/)
- [AWS ECS](https://docs.aws.amazon.com/ecs/)
- `GET /api/v1/health`
- `GET /api/v1/health/db`
- `GET /api/v1/system/info`

## Seeder

Ejecutar y reemplazar datos existentes:
`python -m app.db.seed`

Ejecutar sin borrar datos:
`python -m app.db.seed --keep-existing`

Datos generados por defecto:

- 24 clientes
- 20 usuarios taller + 20 perfiles de taller
- 20 administradores
- 28 vehiculos
- 26 emergencias
- 52 evidencias
- dominio de correo seed: `seed.com`
- contrasena seed: `Seed12345`
