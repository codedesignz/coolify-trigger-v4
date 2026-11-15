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

## Despliegue y validación

1. Con el respaldo verificado, revisa los runs activos y los jobs del agente antes de elegir el momento del cambio. Guarda el Source Compose actual de Webapp en la ubicación restringida de operación. Revisa en Coolify que el cambio de Git del Worker se despliegue después de Webapp.
2. En `teamnet-trigger-eu / production`, edita el **Source Compose** del mismo recurso Webapp (`sk040488wkgwcgo84w8k4gks`). Cambia solo `services.webapp.image` por `ghcr.io/triggerdotdev/trigger.dev:v4.8.5@sha256:6e6d38a94699b93a9be63deb5a8646d5c36fc0e5af60fb9047c5d5ec16e3e92c` y `TRIGGER_CLI_TAG` por `4.8.5`. Conserva los secretos, el valor de `CENTS_PER_RUN`, las redes y los volúmenes del recurso. Revisa el **Deployable Compose**. Si se recrea el recurso completo, comprueba que el comando conserva las imágenes de las dependencias ya observadas. Evita **Pull Latest Images & Restart** para que los tags móviles de PostgreSQL, Redis y MinIO no amplíen el cambio.
3. Despliega Webapp y comprueba el arranque de PostgreSQL, Redis, Electric y ClickHouse si Coolify los recrea. Exige Webapp sana, `/healthcheck` 200, Prisma 868 sin fallidas o incompletas, ambos slots activos y Goose 056.
4. En `trigger-worker1` (`z0wos4o0kg8osw40wc4kkkcg`), despliega la revisión Git que fija el [Compose de Worker](../worker/docker-compose.yml). Comprueba healthcheck, heartbeat y acceso a Docker, broker, registry, S2 y MinIO. Lanza el canario acordado con una versión de tarea ya publicada y verifica estado, salida, logs y coste.
5. Cuando toque actualizar el agente, fija `TRIGGER_CLI_VERSION=4.8.5` solo en `trigger-deploy-agent` y despliega el mismo recurso. Comprueba su consumidor RabbitMQ y publica una versión canaria en Fibra Staging con CLI, SDK y build `4.8.5`. Prueba esa versión antes de promoverla. Las imágenes de tareas que ya estaban publicadas conservan su Node.js hasta que se reconstruyan.

Si Webapp no queda sana, detén el avance y comprueba el estado exacto de Prisma y los bloqueos. Conserva las revisiones e imágenes anteriores. Si hubo migraciones, comprueba la compatibilidad del esquema y del estado escrito antes de volver a `4.8.3`. Para una recuperación con el dump, ensaya primero una restauración aislada y reconcilia PostgreSQL con los runs y colas posteriores a la instantánea. [Recuperación y evidencia del corte anterior](ventana-4.8.3.md)
