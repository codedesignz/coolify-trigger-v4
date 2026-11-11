# Inventario de producción

Inventario verificado por SSH como `root` el 11 de noviembre de 2026. Los nombres de contenedores de aplicaciones pueden incorporar un sufijo nuevo en cada despliegue. Para localizarlos, usa el ID estable del recurso y las etiquetas de Compose.

Las imágenes de las tablas son las observadas en producción. Las recetas versionadas son las candidatas del [plan de actualización a 4.8.3](actualizacion-4.8.3.md).

| Host | Función | Sistema | Capacidad | Disco raíz en la revisión |
| --- | --- | --- | --- | --- |
| `10.21.30.15` · `Tn-Trigger` | Webapp, servicios de datos y aplicaciones auxiliares | Ubuntu 24.04.5 LTS, Docker 29.9.2, Compose 5.6.1 | 8 vCPU, 30 GiB de RAM | ext4, 226 GiB, 72 % usado, 61 GiB libres |
| `10.21.30.16` · `Tn-Trigger-Worker1` | Supervisor, proxy de Docker y runners | Ubuntu 24.04.5 LTS, Docker 29.9.2, Compose 5.6.1 | 8 vCPU, 30 GiB de RAM | ext4, 226 GiB, 7 % usado, 202 GiB libres |

El directorio de datos de Docker es `/var/lib/docker` en ambos hosts. Coolify gestiona `coolify-proxy` (Traefik `v3.7`) y `coolify-sentinel` (`1.1.5`) en cada uno. El Compose del proxy está en `/data/coolify/proxy/docker-compose.yml`.

## 10.21.30.15 · Webapp y datos

En Coolify, busca el proyecto `teamnet-trigger-eu`, entorno `production`, y el recurso `sk040488wkgwcgo84w8k4gks`. Su Compose generado está en `/data/coolify/services/sk040488wkgwcgo84w8k4gks/docker-compose.yml`. La receta versionada está en [webapp/docker-compose.yml](../webapp/docker-compose.yml).

| Servicio | Imagen en ejecución | Rol y acceso |
| --- | --- | --- |
| `webapp` | `ghcr.io/triggerdotdev/trigger.dev:v4.5.4` | UI, API y recepción de OTLP. Traefik enruta `https://trigger.sidicom.es` a `:3000`. Healthcheck en `/healthcheck`. |
| `postgres` | `postgres:16-alpine` | Base transaccional. El stack usa `postgres:5432`. El proxy PostgreSQL de Coolify también publica el puerto del host. |
| `redis` | `redis:7` | Colas y coordinación. Acceso interno `redis:6379`. |
| `electric` | `electricsql/electric:1.2.4` | Sincronización de datos a partir de PostgreSQL. La Webapp usa `http://electric:3000`. Healthcheck en `/v1/health`. |
| `clickhouse` | `clickhouse/clickhouse-server:26.2.19.43` | Eventos de runs, trazas y métricas de Trigger. HTTP `clickhouse:8123` y cliente nativo `:9000` dentro del stack. La Webapp usa `EVENT_REPOSITORY_DEFAULT_STORE=clickhouse_v2`. |
| `s2` | `ghcr.io/s2-streamstore/s2:latest` | Realtime Streams v2 para Sessions y `chat.agent`. API en `http://10.21.30.15:4566/v1`, publicada como `10.21.30.15:4566 → 80/tcp`. El modo lite de la receta usa la red privada para el acceso sin token. |
| `minio` | `bitnamilegacy/minio:latest` | Almacén S3 para objetos y snapshots. API en `http://10.21.30.15:9002`, publicada como `10.21.30.15:9002 → 9000/tcp`. Healthcheck en `/minio/health/live`. El puerto de consola `9001` queda en Docker. |

La red Compose `sk040488wkgwcgo84w8k4gks` conecta el stack y el proxy PostgreSQL. S2 y MinIO también pertenecen a la red local `supervisor` en este host. Las tareas del worker consumen sus direcciones privadas publicadas.

| Recurso auxiliar | Dónde mirar |
| --- | --- |
| `trigger-warm-broker` · `ccem9d0rxqlcc2v8kzvkrob8` | Contenedor `warm-start-broker-*`, versión `0.1.0` con backend Redis. Archivos en `/data/coolify/applications/ccem9d0rxqlcc2v8kzvkrob8/`. El supervisor usa `https://trigger-warm-broker.sidicom.es`. `/healthz` responde por HTTPS y en `http://127.0.0.1:18080/healthz` desde `.15`. |
| `trigger-deploy-agent` · `xc000kcskwwosc00k0wcs8s0` | Contenedores `agent-*` y `rabbitmq-*`. El agente recibe tráfico de Traefik para `https://trigger-deploy.sidicom.es`. Revisa este recurso si falla la automatización de despliegues. |
| Proxy TCP PostgreSQL · `fc4ws4sogks04c84w8ow8sks` | Contenedor Nginx `fc4ws4sogks04c84w8ow8sks-proxy` en Coolify, configuración en `/data/coolify/databases/fc4ws4sogks04c84w8ow8sks/proxy/nginx.conf`. Publica `5432/tcp` en las interfaces IPv4 e IPv6 del host y reenvía a `postgres-sk040488wkgwcgo84w8k4gks:5432`. El alcance desde otras redes depende de los controles de red. |
| Registro de imágenes | La Webapp usa `DEPLOY_REGISTRY_HOST=10.21.30.14:5000` con namespace `trigger`. El servicio de registro está fuera de los dos hosts inventariados. |

### Volúmenes del stack

Coolify antepone `sk040488wkgwcgo84w8k4gks_` a los nombres de la tabla. Usa `docker volume inspect <nombre> --format '{{.Mountpoint}}'` para localizar el punto de montaje real.

| Volumen | Destino | Contenido |
| --- | --- | --- |
| `postgres-data` | `/var/lib/postgresql/data` | PostgreSQL |
| `redis-data` | `/data` | Redis |
| `clickhouse-data-v26-2` | `/var/lib/clickhouse` | ClickHouse activo. Presente el marcador `.trigger-clickhouse-26.2-fresh`. |
| `minio-data` | `/bitnami/minio/data` | Objetos de MinIO |
| `s2-data` | `/data` | Streams de S2 |
| `s2-config` | `/config` | Especificación del basin de S2 |
| `shared` | `/home/node/shared` | Datos de bootstrap de la Webapp, incluido el fichero del token del worker |

`clickhouse-migrate` y `s2-init` son inicializadores de una sola ejecución en la receta. El inventario observó sus resultados persistidos y ningún contenedor activo de esos inicializadores. La receta declara un volumen histórico `clickhouse-data` para la migración Bitnami. El listado local de volúmenes no incluía ese nombre en la revisión. La existencia de backups o copias externas y su capacidad de restauración quedan por verificar en Coolify o en el sistema de backups.

## 10.21.30.16 · Worker

En el mismo proyecto y entorno de Coolify, busca la aplicación `trigger-worker1`, recurso `z0wos4o0kg8osw40wc4kkkcg`. La etiqueta `com.docker.compose.project.config_files` del contenedor señala el Compose del despliegue. En la revisión apuntaba a un checkout temporal de Coolify bajo `/artifacts/`. La receta versionada está en [worker/docker-compose.yml](../worker/docker-compose.yml).

| Servicio | Imagen o nombre | Rol y acceso |
| --- | --- | --- |
| `supervisor` | `ghcr.io/triggerdotdev/supervisor:v4.5.4` | Registra el worker y toma ejecuciones mediante `TRIGGER_API_URL=https://trigger.sidicom.es`. Envía OTLP a `https://trigger.sidicom.es/otel`. La API interna para workloads responde en `supervisor:8020/health`. |
| `docker-proxy` | `tecnativa/docker-socket-proxy:latest` | El supervisor usa `DOCKER_HOST=tcp://docker-proxy:2375`. El proxy monta `/var/run/docker.sock` en solo lectura y permite al supervisor pedir a Docker que cree runners. |
| Runners | `runner-*` | Contenedores de tareas en la red local `supervisor`. En la revisión, los activos usaban imágenes de `10.21.30.14:5000/trigger/…` para `staging` y `production`. Para investigar pulls, contrasta el registry de la imagen concreta con `DOCKER_REGISTRY_URL`, que figura como `registry.sidicom.es` en el supervisor. |

El supervisor y los runners comparten la red bridge local `supervisor`, seleccionada por `DOCKER_RUNNER_NETWORKS=supervisor`. La red del mismo nombre en `.15` es independiente. El supervisor y `docker-proxy` comparten además la red interna `z0wos4o0kg8osw40wc4kkkcg_docker-proxy`. Los puertos `8020` y `2375` carecen de publicación en el host. `8020` es el puerto de la API en uso, aunque los metadatos de la imagen del supervisor declaran `8000/tcp`.

Los runners activos cambian con la actividad. En el momento de la revisión también había contenedores `runner-*` históricos en estado `exited`. Para evaluar un fallo, correlaciona el run concreto y su hora de salida.

## Consultar el estado actual

```bash
ssh root@10.21.30.15
ssh root@10.21.30.16
```

Desde el host pertinente, lista los servicios del proyecto Compose, su estado y sus puertos.

```bash
# Webapp y datos en 10.21.30.15
docker ps -a --filter label=com.docker.compose.project=sk040488wkgwcgo84w8k4gks \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

# Supervisor y proxy en 10.21.30.16
docker ps -a --filter label=com.docker.compose.project=z0wos4o0kg8osw40wc4kkkcg \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

docker network inspect supervisor --format '{{.Name}} {{.Driver}} {{.Scope}}'
```

Para los colectores y las consultas de Grafana, consulta [Observabilidad](observabilidad.md). Para comprobar cada salto desde el host o el supervisor, usa la [guía de diagnóstico](diagnostico.md).
