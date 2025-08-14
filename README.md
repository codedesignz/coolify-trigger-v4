# Trigger v4 (4.0.0-v4-beta.27) en Coolify v4 con Traefik — **Split** Webapp & Worker

Este README explica cómo desplegar **Trigger v4** usando **Coolify v4** con **Traefik**, separando la **Webapp** (servidor `Tn-Trigger`) y el **Worker/Supervisor** (servidor `Tn-Trigger-Worker1`). Además, se contempla un **Registry externo** ya existente (`Tn-Registry`).

> Probado con la plantilla oficial `trigger.dev@4.0.0-v4-beta.27` de Docker Compose como base y adaptado para Coolify (sin `ports:` y aprovechando **Magic Env Vars** como `SERVICE_FQDN_*` y `SERVICE_PASSWORD_64_*`).

---

## 🧱 Requisitos previos

- **Coolify v4** con **Traefik** activo.
- Servidor `Srv-Trigger` (Webapp) y `Srv-Trigger-Worker1` (Worker) añadidos en Coolify y **Healthy**.
- **DNS** apuntando al servidor de `Srv-Trigger` (para el dominio de la Webapp).
- **Docker Registry externo** operativo (`Srv-Registry`), con credenciales.
- (Opcional) Dominio wildcard en Coolify para FQDNs automáticos.

---

## 🚀 Resumen de la arquitectura

- **Webapp**: se expone a Internet vía Traefik de Coolify. Gestiona UI, API, tokens de grupos de workers, etc.
- **Worker (Supervisor)**: **no** expuesto públicamente. Se conecta **saliente** a la Webapp por HTTPS (`TRIGGER_API_URL`) y ejecuta cargas en contenedores efímeros mediante Docker.
- **Servicios internos de la Webapp**: Postgres, Redis, ElectricSQL (Realtime), ClickHouse (métricas), MinIO (object storage) — mismos que en el Compose oficial.

---

## 🧩 Pasos rápidos

1. **Crear recurso “Docker Compose (Raw)”** en Coolify para la **Webapp** (servidor `Tn-Trigger`), pega el YAML de **`webapp`** más abajo.
2. En **Environment** del recurso de la webapp:
   - Genera secretos con Magic Vars (`SERVICE_PASSWORD_64_*`) o pega tus propios valores.
   - Rellena las credenciales del **Registry externo** (`DEPLOY_REGISTRY_*`) si vas a usar deploys desde la Webapp.
3. **Deploy** Webapp y configura el **dominio** generado por `SERVICE_FQDN_WEBAPP_3000` como `APP_ORIGIN/LOGIN_ORIGIN/API_ORIGIN` (ya viene en el YAML).
4. En la Webapp, crea un **Worker Group** y genera un **token** (se muestra una vez). Copia el token.
5. Crea un recurso **Docker Compose (Raw)** para el **Worker** (servidor `Tn-Trigger-Worker1`), pega el YAML de **`worker`** más abajo y en Environment establece:
   - `TRIGGER_API_URL=https://tu-dominio-de-la-webapp`
   - `OTEL_EXPORTER_OTLP_ENDPOINT=https://tu-dominio-de-la-webapp/otel`
   - `TRIGGER_WORKER_TOKEN=<token-copiado>`
   - `MANAGED_WORKER_SECRET=<igual que en la Webapp>`
6. **Deploy** Worker. Verifica en la Webapp que el worker aparece como **online**.

---

## 🔐 Secretos con **Magic Env Vars** (Coolify)

- Usa `SERVICE_PASSWORD_64_SESSION`, `SERVICE_PASSWORD_64_MAGIC`, `SERVICE_PASSWORD_64_ENCRYPTION`, `SERVICE_PASSWORD_64_MANAGED_WORKER`, `SERVICE_PASSWORD_64_POSTGRES`, `SERVICE_PASSWORD_64_MINIO`, `SERVICE_PASSWORD_64_CLICKHOUSE`, etc.
- Coolify los genera una vez por recurso y **mantiene** el mismo valor entre despliegues (útil para que no se invaliden sesiones/tokens sin querer).
- Puedes sustituirlos por valores propios si lo prefieres.

---

## 🧪 Comprobaciones rápidas

- **Webapp**: abre `https://<tu-FQDN>` → crea la cuenta inicial → ve a **Workers** → crea un **Worker Group** y **token**.
- **Worker**: tras el deploy, en la Webapp debería aparecer como **online** en su grupo.
- **Logs**: si el Worker no conecta, revisa `TRIGGER_API_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `TRIGGER_WORKER_TOKEN` y que el server tiene salida a Internet.

---

## 🧰 `env.example` por stack

Guárdalos para referencia si desplegarás desde Git; en **Raw Compose** de Coolify no son necesarios, ya que las variables se definen en la UI.

### `.env.webapp.example`

```env
# --- Versiones ---
TRIGGER_IMAGE_TAG=v4.0.0-v4-beta.27
POSTGRES_IMAGE_TAG=14
REDIS_IMAGE_TAG=7
ELECTRIC_IMAGE_TAG=1.0.24
CLICKHOUSE_IMAGE_TAG=latest
MINIO_IMAGE_TAG=latest

# --- Secrets (si no usas Magic Vars de Coolify) ---
SESSION_SECRET=
MAGIC_LINK_SECRET=
ENCRYPTION_KEY=
MANAGED_WORKER_SECRET=

# --- Postgres ---
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
POSTGRES_DB=postgres
DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/main?schema=public&sslmode=disable
DIRECT_URL=postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/main?schema=public&sslmode=disable

# --- Object Storage (MinIO interno por defecto) ---
OBJECT_STORE_BASE_URL=http://minio:9000
OBJECT_STORE_ACCESS_KEY_ID=admin
OBJECT_STORE_SECRET_ACCESS_KEY=

# --- ClickHouse / Replicación ---
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_URL=http://default:${CLICKHOUSE_PASSWORD}@clickhouse:8123?secure=false
RUN_REPLICATION_ENABLED=1
RUN_REPLICATION_CLICKHOUSE_URL=http://default:${CLICKHOUSE_PASSWORD}@clickhouse:8123

# --- Registry externo (Tn-Registry) para deploys ---
DEPLOY_REGISTRY_HOST=
DEPLOY_REGISTRY_NAMESPACE=trigger
DEPLOY_REGISTRY_USERNAME=
DEPLOY_REGISTRY_PASSWORD=

# --- Otros ---
APP_LOG_LEVEL=info
TRIGGER_BOOTSTRAP_ENABLED=0
```

### `.env.worker.example`

```env
# --- Versiones ---
TRIGGER_IMAGE_TAG=v4.0.0-v4-beta.27
DOCKER_PROXY_IMAGE_TAG=latest

# --- Conexión a la Webapp ---
TRIGGER_API_URL=https://trigger.example.com
OTEL_EXPORTER_OTLP_ENDPOINT=https://trigger.example.com/otel

# --- Auth del Worker ---
TRIGGER_WORKER_TOKEN=
MANAGED_WORKER_SECRET=

# --- Registry (si privado) ---
DOCKER_REGISTRY_URL=
DOCKER_REGISTRY_USERNAME=
DOCKER_REGISTRY_PASSWORD=

# --- Opcionales ---
DEBUG=1
ENFORCE_MACHINE_PRESETS=1
TRIGGER_DEQUEUE_INTERVAL_MS=1000
```

---

## 🐞 Troubleshooting

- **El Worker no aparece online**:
  - Revisa `TRIGGER_WORKER_TOKEN` (que no tenga espacios ni saltos).
  - Comprueba `TRIGGER_API_URL` y `OTEL_EXPORTER_OTLP_ENDPOINT` (HTTPS válidos).
  - Asegura salida a Internet desde `Tn-Trigger-Worker1`.
- **Errores al build/pull de imágenes para runs**:
  - Configura `DOCKER_REGISTRY_*` en el Worker y haz `docker login` si usas imágenes privadas.
- **Enlaces de login por email**:
  - Si no configuras proveedor (`EMAIL_TRANSPORT`), los magic links quedan en logs de la Webapp.
- **Cambiaste `SESSION_SECRET`**:
  - Se invalidarán sesiones existentes. Evítalo en producción.
- **CORS/orígenes**:
  - Usa siempre el mismo dominio en `APP_ORIGIN/LOGIN_ORIGIN/API_ORIGIN` (en este README ya se derivan de `SERVICE_FQDN_WEBAPP_3000`).

---

## 📎 Notas

- Este README asume **split setup**: por eso **no** hay volumen `shared:/home/node/shared` ni `user: root`/`chown`, ni `TRIGGER_WORKER_TOKEN=file://...`.
- Si un día ejecutas **todo en el mismo host**, puedes restaurar el `shared` y el “bootstrap” (`TRIGGER_BOOTSTRAP_ENABLED=1`) para que el token se deposite en fichero.

---

¡Listo! Copia/pega los YAML en Coolify y rellena las variables mínimas. Si quieres, añade también una versión **sin ClickHouse/MinIO** apuntando a servicios externos.
