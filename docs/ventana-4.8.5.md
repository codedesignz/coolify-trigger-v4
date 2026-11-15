# TriggerEU de 4.8.3 a 4.8.5

El 15 de noviembre el preflight de TriggerEU encontró Webapp y Supervisor `4.8.3` sanos, PostgreSQL `16.16` con 856 migraciones Prisma y ninguna incompleta, y ambos slots activos. PostgreSQL ocupaba 52 GB y el Cloud Volume de Hetzner tenía 91 GiB disponibles. El agente usaba CLI `4.5.4`.

El salto directo incorpora las 12 migraciones Prisma de `4.8.4`. Añaden columnas, tres índices concurrentes y las tablas de publicación de confianza. Las tablas existentes afectadas son pequeñas en TriggerEU. Los directorios de migraciones de Drizzle, Run Ops y ClickHouse son idénticos en ambos tags. Goose permanece en `056` y Search v2 conserva el histórico. `4.8.5` actualiza Node.js en Webapp, Supervisor y las imágenes de tareas que se publiquen con la CLI nueva. [Release 4.8.4](https://github.com/triggerdotdev/trigger.dev/releases/tag/v4.8.4) · [Release 4.8.5](https://github.com/triggerdotdev/trigger.dev/releases/tag/v4.8.5)

## Respaldo de PostgreSQL

En `Tn-Trigger`, abre una sesión SSH con acceso a Docker y ejecuta este bloque. El dump toma una instantánea consistente con los servicios disponibles. `verified.utc` confirma que se leyó todo el archivo sin restaurarlo y que coincidieron los SHA-256. Si se usa la copia para recuperar, reconcilia las escrituras posteriores a la instantánea.

```sh
set -eu
umask 077
volume=/mnt/HC_Volume_107434992
mountpoint -q "$volume"
pg=postgres-sk040488wkgwcgo84w8k4gks
test "$(docker inspect --format '{{.State.Health.Status}}' "$pg")" = healthy
test "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$pg")" = sk040488wkgwcgo84w8k4gks
root="$volume/trigger-eu-rollback"
test -d "$root"
cut=$(mktemp -d "$root/trigger-pg-pre485-$(date -u +%Y%m%dT%H%M%SZ).XXXXXXXX")
printf 'Respaldo en %s\n' "$cut"
date -u +%FT%TZ > "$cut/start.utc"
docker exec "$pg" sh -ec 'exec pg_dump -Fc -Z1 --lock-wait-timeout=15s -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$cut/postgres.dump.part"
docker exec "$pg" sh -ec 'exec pg_dumpall --globals-only --no-role-passwords -U "$POSTGRES_USER"' > "$cut/globals.sql"
docker exec -i "$pg" pg_restore --list < "$cut/postgres.dump.part" > "$cut/postgres.list"
test -s "$cut/postgres.list"
docker exec -i "$pg" pg_restore --exit-on-error --file=/dev/null < "$cut/postgres.dump.part"
mv "$cut/postgres.dump.part" "$cut/postgres.dump"
(
  cd "$cut"
  sha256sum postgres.dump globals.sql postgres.list > SHA256SUMS
  sha256sum -c SHA256SUMS
)
date -u +%FT%TZ > "$cut/verified.utc"
du -h "$cut/postgres.dump"
printf 'Respaldo verificado en %s\n' "$cut"
```

El 15 de noviembre se obtuvo un dump de **6,9 GiB** en `/mnt/HC_Volume_107434992/trigger-eu-rollback/trigger-pg-pre485-20261115T092918Z.wu1dTSNz/postgres.dump`. La copia arrancó a las **10:29:18 CET** y quedó verificada a las **10:43:20 CET**. `pg_restore` leyó todo el archivo y `sha256sum -c` validó el dump, los objetos globales y el listado. La API siguió respondiendo `200` en las sondas y Prisma conservaba 856 migraciones aplicadas y ninguna incompleta.

## Despliegue y validación

1. Con el respaldo verificado, revisa los runs activos y los jobs del agente antes de elegir el momento del cambio. Guarda el Source Compose actual de Webapp en la ubicación restringida de operación. Revisa en Coolify que el cambio de Git del Worker se despliegue después de Webapp.
2. En `teamnet-trigger-eu / production`, abre el recurso Webapp (`sk040488wkgwcgo84w8k4gks`) y elige **Configuration → General → Edit Compose File → Source Compose**. Aplica las entradas de la tabla de abajo a los bloques existentes. Conserva los secretos, `CENTS_PER_RUN=0.03867`, las redes y los volúmenes del recurso. Revisa el **Deployable Compose** antes de desplegar. **Deploy** opera sobre todo el recurso y puede recrear sus dependencias. Los digests de PostgreSQL, Redis y MinIO fijan las mismas imágenes observadas antes del cambio. [Operación de servicios en Coolify](https://coolify.io/docs/services/how-services-work)
3. Despliega Webapp y comprueba el arranque de PostgreSQL, Redis, Electric y ClickHouse si Coolify los recrea. Exige Webapp sana, `/healthcheck` 200, Prisma 868 sin fallidas o incompletas, ambos slots activos y Goose 056.
4. En `trigger-worker1` (`z0wos4o0kg8osw40wc4kkkcg`), despliega la revisión Git que fija el [Compose de Worker](../worker/docker-compose.yml). Comprueba que el socket proxy conserva la imagen observada `tecnativa/docker-socket-proxy:latest@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459`. Verifica healthcheck, heartbeat y acceso a Docker, broker, registry, S2 y MinIO. Lanza el canario acordado con una versión de tarea ya publicada y verifica estado, salida, logs y coste.
5. Cuando toque actualizar el agente, fija `TRIGGER_CLI_VERSION=4.8.5` solo en `trigger-deploy-agent` y despliega el mismo recurso. Comprueba su consumidor RabbitMQ y publica una versión canaria en Fibra Staging con CLI, SDK y build `4.8.5`. Prueba esa versión antes de promoverla. Las imágenes de tareas que ya estaban publicadas conservan su Node.js hasta que se reconstruyan.

| Entrada en Source Compose | Valor |
| --- | --- |
| `webapp.image` | `ghcr.io/triggerdotdev/trigger.dev:v4.8.5@sha256:6e6d38a94699b93a9be63deb5a8646d5c36fc0e5af60fb9047c5d5ec16e3e92c` |
| `webapp.environment` | `TRIGGER_CLI_TAG=4.8.5` |
| `postgres.image` | `postgres:16-alpine@sha256:f377d590e5474681d4d7838635031a2b50647923b7abfa803ce9b5ff35d5c663` |
| `redis.image` | `redis:7@sha256:2e3eb11462c4e3759e6972678dd051d150ff54b1e60714b3c33b701260172a90` |
| `minio.image` | `bitnamilegacy/minio:latest@sha256:451fe6858cb770cc9d0e77ba811ce287420f781c7c1b806a386f6896471a349c` |

Si Webapp no queda sana, detén el avance y comprueba el estado exacto de Prisma y los bloqueos. Conserva las revisiones e imágenes anteriores. Si hubo migraciones, comprueba la compatibilidad del esquema y del estado escrito antes de volver a `4.8.3`. Para una recuperación con el dump, ensaya primero una restauración aislada y reconcilia PostgreSQL con los runs y colas posteriores a la instantánea. [Recuperación y evidencia del corte anterior](ventana-4.8.3.md)

## Validación de Webapp

Webapp `4.8.5` arrancó el 15 de noviembre a las **10:55:29 CET** con el digest previsto, Node.js `24.22.3` y cero reinicios. `/healthcheck` devolvió `200` en local, por HTTPS y desde el Supervisor. Sessions y Realtime devolvieron `401` JSON en las sondas anónimas. Se conservaron `CENTS_PER_RUN=0.03867`, Search v2 y la replicación. Coolify recreó las dependencias con los mismos IDs de imagen observados antes del cambio.

Prisma pasó de **856 a 868** migraciones, sin incompletas ni índices nuevos inválidos. Drizzle conservó 9 migraciones y ClickHouse registró Goose `056` sobre el volumen activo `clickhouse-data-v26-2` con el marcador `fresh`. Los slots de Electric y de runs estaban activos. Tras el arranque se observaron tres runs ordinarios completados. Una muestra coincidió entre PostgreSQL y ClickHouse en estado y coste, con 78 eventos en Search v2.

Supervisor seguía sano en `4.8.3`, con heartbeats y acceso al broker, Docker, registry, S2 y MinIO. La rama `main` que usa el recurso de Worker contiene la receta candidata desde `db8b9c1`. El digest que resuelve `latest` del proxy Docker coincidió con la imagen efectiva antes del siguiente despliegue.

## Validación del Supervisor

Supervisor `4.8.5` arrancó el 15 de noviembre a las **11:03:32 CET** desde `00c61b2`, con el digest previsto, Node.js `24.22.3` y cero reinicios. El proxy Docker mantuvo el digest anterior. El Supervisor nuevo se registró en `bootstrap` a las **11:03:35 CET** y siguió enviando heartbeats. Respondieron Webapp, Docker, broker y MinIO. Las sondas a S2 y al registry devolvieron los códigos esperados.

Los primeros tres runs ordinarios en Fibra, uno de producción y dos de staging, completaron con arranque en frío. Se contrastaron con los logs del Supervisor y una muestra coincidió entre PostgreSQL y ClickHouse en estado y coste (**USD 0.0003867 por invocación**), con eventos en Search v2. El siguiente paso es cambiar el agente a CLI `4.8.5` y probar la publicación. En la revisión el agente mantenía CLI `4.5.4` y `deploy_queue` de RabbitMQ tenía cero mensajes listos o sin confirmar y un consumidor.

## Validación del agente de despliegue

El contenedor de `trigger-deploy-agent` arrancó el 15 de noviembre a las **11:10:36 CET** con `TRIGGER_CLI_VERSION=4.8.5`, código `ecaba943` y cero reinicios. El agente y RabbitMQ estaban sanos, su ruta HTTPS `/health` devolvía `200` y `deploy_queue` tenía un consumidor y cero mensajes listos o sin confirmar. En la consulta posterior al arranque no había publicaciones nuevas, por lo que queda pendiente ejecutar un job.

Para la prueba, toma como base el despliegue de Fibra Staging `20261112.1` (commit `12618d7` de `trigger-simple`). El manifiesto de ese commit declara `@trigger.dev/sdk`, `@trigger.dev/build` y `trigger.dev` en `4.4.4`. El despliegue registrado usó SDK y CLI `4.5.4`. Prepara una revisión dedicada con los tres paquetes y el lockfile alineados en `4.8.5` antes de enviar el job. El agente instala dependencias y ejecuta el CLI configurado en CI, donde el chequeo de versiones puede abortar si hay diferencias. [Chequeo de versiones de CLI 4.8.5](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.5/packages/cli-v3/src/commands/update.ts)

Usa un job individual del agente con `projectRef=proj_tgaeqppbuwskratyvwwu`, `environment=staging` y la rama dedicada. El comando del agente promociona la versión en Staging. Reserva esa prueba para el momento en que Fibra Staging pueda recibir el nuevo despliegue. El flujo genérico de `stage` también publica en otros entornos. Comprueba el job, la versión desplegada y la ejecución de `hello-world`.

## Retirada del volumen temporal

El 15 de noviembre a las **11:37:35 CET**, se desmontó en Tn-Trigger el Cloud Volume `107434992` de `/mnt/HC_Volume_107434992`. Tras el borrado en Hetzner, se confirmó por SSH la ausencia del montaje y del dispositivo. A las **11:47:11 CET**, se retiró la entrada del volumen de `/etc/fstab`, se validó el archivo con `findmnt` y se recargó la configuración de systemd. La API respondió `200`. La copia previa de `/etc/fstab` quedó en `/root/fstab-before-volume-107434992-20261115T104711Z.i2WcHp3T` en Tn-Trigger.

El backup de PostgreSQL posterior a `4.8.5`, iniciado desde Coolify a las **11:28:38 CET**, terminó a las **11:41:39 CET** en el disco principal, bajo `/data/coolify/backups/databases/teamnet-4/trigger-postgres-sk040488wkgwcgo84w8k4gks/`. El archivo `pg-dump-trigger-1794738518-kewqqafrarevoe4jmgpdcx6p.dmp` mide **4,55 GiB**. `pg_restore` confirmó la base `trigger`, un índice de 1.250 entradas y una lectura completa sin errores a las **11:44:02 CET**.
