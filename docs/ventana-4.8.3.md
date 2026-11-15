# Preparación del corte de TriggerEU a 4.8.3

Ruta operativa con **Coolify y SSH** para `teamnet-trigger-eu / production`. El corte afecta a la API común y al Supervisor que atiende `production`, `staging` y cualquier Preview que use su worker group. Los despliegues y la recuperación siguen el [plan 4.8.3](actualizacion-4.8.3.md).

## Preflight del 11 de noviembre de 2026

| Comprobación | Observación del preflight |
| --- | --- |
| Plataforma | Webapp y Supervisor sanos en `4.5.4`. Dependencias, broker Redis, agente y RabbitMQ sanos. Las sondas de red devolvieron los códigos esperados. El Compose efectivo validó con `config --quiet`. |
| Almacenamiento | Ambos hosts son invitados KVM con ext4 en `/dev/sda1`. En `.15` quedaban 60 GiB y en `.16`, 204 GiB. PostgreSQL y ClickHouse ocupaban juntos 102,5 GB físicos. Después se añadió el Cloud Volume de Hetzner descrito abajo. |
| PostgreSQL | Hay `pg_basebackup` y `pg_verifybackup` 16.15. `archive_mode=off`. Dos slots lógicos activos. El dump diario de las 03:00 UTC tiene TOC legible, mide 4,88 GB y se restauró en el ensayo. El preflight posterior confirmó 586 entradas en un dump de solo esquema y acceso a los metadatos globales. |
| ClickHouse | `26.2.19.43`, volumen `clickhouse-data-v26-2` con marcador `fresh`. El ZIP probado contiene `trigger_dev` y `default.goose_db_version`, mide 920 MB y se capturó a las 09:09 UTC. Excluir los logs de `system` evita copiar unos 40 GB. El cliente del contenedor confirmó permiso de backup sobre ambos objetos. |
| Entornos y schedules | 7 entornos de producción, 7 de staging y 8 Preview sin pausar en la lectura. Se observaron 3 schedules declarativos activos en producción y 7 en staging. Confirma qué Preview comparte el worker group antes del corte. |
| Runs recientes | En 24 h se observaron 440 runs terminados en producción y 987 en staging. El p95 entre primera ejecución y fin fue 2,4 s y 6,0 s respectivamente. La consulta acotada no encontró runs no terminales creados en esas 24 h. En la ventana hay que comprobar también waits y backlog anteriores. |
| Despliegues | RabbitMQ vhost `/`, cola `deploy_queue`, 0 listos, 0 sin confirmar y 1 consumidor. El agente usa CLI `4.4.4`. |
| Acceso de entrada | Traefik enruta API y OTLP por el mismo host `trigger.sidicom.es`. El agente y el broker tienen rutas independientes. El proxy PostgreSQL publica `5432` en IPv4 e IPv6 y la muestra no mostró sesiones a través de él. |
| Destino | El DRON SSD se usó para los ensayos locales. El respaldo del corte se guardará en el Cloud Volume `107434992` montado en `Tn-Trigger`. |

El archivo PostgreSQL de las 03:00 y el ZIP de las 09:09 corresponden a fronteras distintas. Sirven como copias de referencia para el ensayo. La ventana necesita sus propios artefactos del mismo corte.

### Comprobación del 13 de noviembre de 2026

A las 11:08 CET, Webapp y Supervisor seguían sanos en `4.5.4`. PostgreSQL `16.15` ocupaba 51,9 GiB y tenía dos slots lógicos activos, cero bloqueos y cero backups en ejecución. ClickHouse seguía en `26.2.19.43` con Goose `35`. Había **96,6 GiB libres** en el volumen de recuperación y **59,8 GiB libres** en el disco activo de Tn-Trigger. Las imágenes fijadas de Webapp y Supervisor `4.8.3` aún no estaban en la caché de sus hosts.

A las 11:35 CET quedó descargada la imagen fijada de Webapp `4.8.3` para `linux/amd64` en Tn-Trigger. Docker verificó el digest de la receta y registró el ID de imagen `sha256:1c6783a35bfcbbb8ce2740cd8f44dc14fec175ec75976937fa3fe5efd66c89ab`. Tras la descarga, la Webapp `4.5.4` seguía sana y `/healthcheck` devolvió `200`.

En los últimos 15 minutos se crearon cuatro runs de producción y diez de staging. Ninguno seguía pendiente o en ejecución en la lectura. Quedaban ocho registros anteriores a un día en `PENDING` o `DEQUEUED`, y `deploy_queue` tenía cero listos y cero sin confirmar. Grafana registró dos HTTP `502` en OTLP a las 10:56 CET. Las 368 respuestas de los últimos cinco minutos fueron `200`. [Logs de TriggerEU](https://grafana.sidicom.es/d/ceexp8uiaujgga/coolify-logs-explorer?var-project=TriggerEU&var-environment=Prod)

## Punto de recuperación con los accesos actuales

Guarda el respaldo del corte en un directorio privado y único de `/mnt/HC_Volume_107434992`, separado de los datos activos de Docker. Captura PostgreSQL, ClickHouse y los volúmenes auxiliares con los escritores detenidos y verifica los archivos desde ese montaje antes del DDL. El respaldo del corte queda disponible para revertir la actualización mientras el volumen sea accesible. Los snapshots y backups de servidores de Hetzner excluyen los Cloud Volumes adjuntos. [Cloud Volumes de Hetzner](https://docs.hetzner.com/cloud/volumes/overview/)

| Artefacto | Captura tras drenar y cerrar escrituras | Qué se restaura |
| --- | --- | --- |
| PostgreSQL | Capturar con `pg_dump` y guardar los metadatos globales. Para la ruta física, añadir `pg_basebackup -Fp -X stream` y verificarlo con `pg_verifybackup` en el volumen de Hetzner. Registrar publicaciones, slots lógicos y LSN. | Clúster PostgreSQL 16 con base `trigger`, roles/ACL y publicaciones. Comprobar los slots y la reanudación de Electric y de la réplica de runs. |
| ClickHouse | Backup nativo de `trigger_dev` y `default.goose_db_version` en un ZIP único con la imagen actual. Conservar la información del volumen y marcador. | Datos y journal sobre `26.2.19.43`. Restaurar en volumen preparado y comprobar Search v1, raw y marcador. |
| Redis de TriggerEU y broker | Tras parar escritores, ejecutar `BGSAVE`, esperar `rdb_bgsave_in_progress:0` y `rdb_last_bgsave_status:ok` con `LASTSAVE` posterior al valor previo. Capturar `redis-data` con el servicio detenido. En la revisión solo había RDB y el broker usaba este Redis. | RDB del corte y configuración actual. Verificar colas, estados y el prefijo del broker con los consumidores aún en pausa. |
| S2, MinIO y bootstrap | Parar sus escritores y capturar `s2-data`, `s2-config`, `minio-data` y `shared`. Guardar configuración de dominios y secretos en su ubicación restringida. | Streams, objetos y snapshots de la frontera común, basin y bootstrap de Worker. |
| RabbitMQ y agente | Cerrar la entrada HTTP/AMQP y esperar que `deploy_queue` quede con 0 listos y 0 sin confirmar. Detener el consumidor y capturar el volumen de RabbitMQ detenido. Registrar si el workspace del agente se recrea desde Git/registry o requiere archivo propio. | Definiciones, cola y estado que se haya acordado retener. Conservar imágenes de tareas y la configuración anterior del agente. |

Se ensayó el arranque de una copia física de PostgreSQL en el volumen de Hetzner y la restauración lógica de PostgreSQL y del ZIP de ClickHouse en local. Conserva el ZIP nativo para limitar la captura de ClickHouse a las bases y el journal del servicio. [Backup físico PostgreSQL 16](https://www.postgresql.org/docs/16/app-pgbasebackup.html) · [Backup de ClickHouse](https://clickhouse.com/docs/concepts/features/backup-restore/overview)

### Volumen de recuperación en Tn-Trigger

El Cloud Volume de **160 GiB** ya está montado en `Tn-Trigger`. Antes del corte, comprueba el dispositivo y los bytes libres tanto en ese volumen como en el disco activo de Docker. Dos copias físicas de PostgreSQL consumen unos 104 GiB al tamaño observado. Reserva margen para WAL, el ZIP nativo de ClickHouse y los archivos auxiliares. Las migraciones y el backfill usan los volúmenes activos.

Verifica la nueva copia base con `pg_verifybackup` y consérvala intacta. Si el rollback activa PostgreSQL desde una copia de trabajo en este volumen, retén el disco hasta devolver los datos a almacenamiento definitivo. [Verificación de backups físicos](https://www.postgresql.org/docs/16/app-pgverifybackup.html)

El 11 de noviembre se verificó por SSH el volumen `107434992` en `/mnt/HC_Volume_107434992`, en EXT4 y con **148,4 GiB disponibles**. `fstab` usa el identificador estable `/dev/disk/by-id/scsi-0HC_Volume_107434992`. La prueba de escritura con `fsync` y lectura pasó y se retiró el archivo temporal. Webapp, PostgreSQL y ClickHouse seguían sanos con 13 días de actividad.

Ese día, de **14:37:52 a 15:22:06** en hora peninsular, `pg_basebackup` de PostgreSQL 16.15 copió **51,8 GiB** con WAL en **44 min 14 s**, con `--max-rate=20M` y checkpoint distribuido. La copia del ensayo quedó en `/mnt/HC_Volume_107434992/trigger-eu-rollback/20261111T133752Z/base`, con salida cero, manifiesto y WAL presentes. Las 43 sondas de salud devolvieron `200` y las ventanas de Traefik observadas registraron cero HTTP 5xx.

`pg_verifybackup` de PostgreSQL 16.15 verificó el manifiesto, los archivos y el WAL requerido en **5 min 37 s**. El contenedor usó red `none` y montó la copia en solo lectura. La verificación terminó con salida cero y las sondas de la API devolvieron `200`.

La copia de trabajo `work-20261111T143543Z` se preparó y sincronizó en **22 min 13 s** con `rsync` limitado a 40 MiB/s. El contenedor aislado de PostgreSQL 16.15, con red `none` y socket Unix, aplicó el WAL y respondió a la primera consulta fuera de recuperación en **703 ms** desde el arranque. Se leyeron 100 runs y 795 migraciones Prisma aplicadas, con cero pendientes y cero índices inválidos. El clon conservó dos publicaciones y presentó cero slots lógicos. Prepara la reanudación de Electric y de la réplica de runs antes del corte. El contenedor de ensayo se cerró y retiró. La copia base conserva su manifiesto original. Con ambas copias quedan **45 GiB libres** en el volumen. La API respondió `200` en las 22 sondas de la duplicación y en la sonda posterior al arranque.

Se retiró únicamente `work-20261111T143543Z` después del ensayo. Se recuperaron **51,8 GiB** y el volumen quedó con **96,6 GiB libres**. El SHA-256 del manifiesto de `base` coincidió con el anterior y `/healthcheck` respondió HTTP `200`.

Con esa capacidad hay dos rutas. Para rollback físico, cabe una copia base nueva de unos 52 GiB y los archivos compactos del corte. Para disponer además de una copia de trabajo en el mismo volumen, recupera espacio antes del DDL. Una opción es retirar la base del ensayo del 11 de noviembre tras verificar la base nueva y con el acuerdo del operador. Para rollback lógico, guarda el dump y los demás archivos compactos, y reserva espacio en el volumen para restaurar PostgreSQL en un directorio separado. Dimensiona ambas rutas con la capacidad efectiva y acuerda el tiempo de recuperación antes de pausar el servicio.

### Recuperación de Electric y de la réplica de runs

La lectura del 11 de noviembre encontró `electric_slot_default` y `task_runs_to_clickhouse_v1` activos en la base `trigger` con `pgoutput` y `wal_level=logical`. Electric `1.2.4` respondió HTTP `200` en `/v1/health` y el contenedor tenía cero montajes. Su publicación era `electric_publication_default`, con cero tablas en esa lectura. La Webapp usa `RUN_REPLICATION_ENABLED=1`, los nombres por defecto y el ClickHouse del recurso. `task_runs_to_clickhouse_v1_publication` publica INSERT, UPDATE y DELETE de `public."TaskRun"` sin filtro. `TaskRun` usa identidad de réplica `FULL`. No hay suscripciones nativas de PostgreSQL.

En una muestra acotada del mismo día, **9 runs de producción y 18 de staging** coincidieron por ID interno, entorno, estado y hora de actualización entre PostgreSQL y `trigger_dev.task_runs_v2 FINAL`. Es una referencia de esa lectura. Para el corte incluye también runs anteriores que hayan cambiado en el intervalo y cualquier run que cambie durante el drenaje.

1. **Fijar la frontera de las réplicas**. Cierra las entradas, drena los runs y deja que Webapp termine de enviar los lotes a ClickHouse. Registra `restart_lsn` y `confirmed_flush_lsn`, comprueba los errores de inserción y contrasta los IDs afectados antes de detener Webapp y Electric. Repite la comparación para cualquier escritura detectada al fijar la frontera. En 4.5.4 el ACK del slot puede avanzar antes de que ClickHouse confirme la inserción. Guarda PostgreSQL, ClickHouse y Redis de la misma frontera. El `_version` de `task_runs_v2` deriva del LSN y una copia de ClickHouse posterior puede conservar una versión superior del run tras la reversión. [ACK e inserción en Trigger.dev](https://github.com/triggerdotdev/trigger.dev/blob/v4.5.4/apps/webapp/app/services/runsReplicationService.server.ts#L602-L739) · [Versionado de runs](https://github.com/triggerdotdev/trigger.dev/blob/v4.5.4/internal-packages/clickhouse/schema/004_create_task_runs_v2.sql#L70-L76)
2. **Restaurar y recrear consumidores**. Mantén las entradas ordinarias cerradas. Verifica `wal_level=logical`, las dos publicaciones y sus permisos en PostgreSQL. Tras recuperar las dependencias, recrea Electric `1.2.4` desde su receta anterior con una capa de escritura nueva. Electric crea `electric_slot_default` y reconstruye sus shapes desde PostgreSQL. Arranca Webapp `4.5.4` con su receta anterior y el destino ClickHouse restaurado. Webapp crea `task_runs_to_clickhouse_v1` al suscribirse si falta. Si el lock de Redis de la réplica sigue presente, espera su caducidad normal y verifica el liderazgo. Cada slot nuevo empieza en su posición inicial. [Recreación en Electric 1.2.4](https://github.com/electric-sql/electric/blob/94fe66624b2f4c3fca08dc05c6bf49317ce97a49/packages/sync-service/lib/electric/postgres/replication_client/connection_setup.ex#L142-L170) · [Estado de shapes](https://github.com/electric-sql/electric/blob/94fe66624b2f4c3fca08dc05c6bf49317ce97a49/packages/sync-service/lib/electric/connection/manager.ex#L426-L474) · [Slot de Trigger.dev](https://github.com/triggerdotdev/trigger.dev/blob/v4.5.4/internal-packages/replication/src/client.ts#L745-L775)
3. **Probar antes de reabrir**. Exige ambos slots activos y Electric con HTTP `200` y estado `active`. Con el canario de `staging`, verifica que un cliente autenticado vuelve a cargar una shape anterior si recibe `409 must-refetch`, y que recibe la actualización de un run. Comprueba ese run en PostgreSQL, `task_runs_v2 FINAL` y el panel. Contrasta los runs de la frontera. Si hay diferencias, identifica primero los IDs y estados afectados. El backfill de administración en 4.5.4 selecciona por `createdAt` y estados terminales y vuelve a insertar payloads. Acota cualquier reparación al hueco comprobado y verifica el resultado antes de reabrir. [Salud de Electric](https://github.com/electric-sql/electric/blob/94fe66624b2f4c3fca08dc05c6bf49317ce97a49/packages/sync-service/lib/electric/plug/health_check_plug.ex#L16-L37) · [Recarga de shape](https://github.com/electric-sql/electric/blob/94fe66624b2f4c3fca08dc05c6bf49317ce97a49/packages/sync-service/lib/electric/shapes/api.ex#L299-L308) · [Filtro de backfill 4.5.4](https://github.com/triggerdotdev/trigger.dev/blob/v4.5.4/apps/webapp/app/services/runsBackfiller.server.ts#L43-L69)

Para un run concreto, usa su ID interno y compara `status` y el instante UTC de `updated_at`. Estas consultas se ejecutan con `psql -v run_id=…` y `clickhouse-client --param_run_id=… --param_env_id=…`, respectivamente.

```sql
SELECT id, "runtimeEnvironmentId", status, "updatedAt"
FROM public."TaskRun" WHERE id = :'run_id';
```

```sql
SELECT run_id, environment_id, status, updated_at
FROM trigger_dev.task_runs_v2 FINAL
WHERE run_id = {run_id:String} AND environment_id = {env_id:String} AND _is_deleted = 0;
```

La revisión confirmó las sondas en producción y los mecanismos en el código fijado. La recreación de ambos slots y la entrega de un canario tras restaurar PostgreSQL quedan por ensayar de forma aislada.

### Captura de referencia durante la ventana

Ejecuta estos comandos en `.15` una vez fijada la frontera, detenido el tráfico de escritura y pausadas las fusiones TTL de raw v2 y Search v1. Deja activas las fusiones ordinarias. Se usan los contenedores de datos ya en marcha y la autenticación interna. El bloque prepara el destino privado y toma la copia lógica. Para la copia física usa el mismo directorio de corte y la misma ruta de replicación local del ensayo. Registra la salida de `pg_verifybackup` antes de seguir.

```bash
set -euo pipefail
umask 077

project=sk040488wkgwcgo84w8k4gks
volume=/mnt/HC_Volume_107434992
device=/dev/disk/by-id/scsi-0HC_Volume_107434992
test "$(hostname -s)" = Tn-Trigger
test "$(findmnt -rn --mountpoint "$volume" -o FSTYPE)" = ext4
test "$device" -ef "$(findmnt -rn --mountpoint "$volume" -o SOURCE)"
df -hT -- "$volume"
cut_id="trigger-cut-$(date -u +%Y%m%dT%H%M%SZ)"
cut_dir="$volume/trigger-eu-rollback/$cut_id"
test ! -e "$cut_dir"
mkdir -m 700 -- "$cut_dir"

pg=$(docker ps -q --filter "label=com.docker.compose.project=$project" \
  --filter label=com.docker.compose.service=postgres)
ch=$(docker ps -q --filter "label=com.docker.compose.project=$project" \
  --filter label=com.docker.compose.service=clickhouse)
test -n "$pg"
test -n "$ch"
test "$(printf '%s\n' "$pg" | wc -l)" -eq 1
test "$(printf '%s\n' "$ch" | wc -l)" -eq 1
date -u +%FT%TZ > "$cut_dir/backup-start.utc"

docker exec -i "$pg" sh -ec 'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "$cut_dir/postgres-replication.txt" <<'SQL'
SELECT pg_current_wal_lsn();
SELECT slot_name, plugin, database, active, restart_lsn, confirmed_flush_lsn
FROM pg_replication_slots ORDER BY slot_name;
SELECT pubname, puballtables FROM pg_publication ORDER BY pubname;
SQL

docker exec "$pg" sh -ec 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "$cut_dir/postgres.dmp.part"
test -s "$cut_dir/postgres.dmp.part"
docker exec -i "$pg" pg_restore --list < "$cut_dir/postgres.dmp.part" \
  > "$cut_dir/postgres.toc"
mv "$cut_dir/postgres.dmp.part" "$cut_dir/postgres.dmp"
docker exec "$pg" sh -ec 'exec pg_dumpall --globals-only --no-role-passwords -U "$POSTGRES_USER"' \
  > "$cut_dir/postgres-globals.sql"
```

Para ClickHouse, conserva el ID y espera `BACKUP_CREATED` antes de transferir el archivo. Los comandos usan el mismo formato de backup que se restauró en el SSD.

```bash
docker exec "$ch" clickhouse-client -q \
  "BACKUP DATABASE trigger_dev, TABLE default.goose_db_version
   TO File('$cut_id.zip')
   SETTINGS id='$cut_id', max_backup_bandwidth=20971520 ASYNC"

docker exec "$ch" clickhouse-client -q \
  "SELECT status, compressed_size, start_time, end_time
   FROM system.backups WHERE id='$cut_id'"
```

Localiza el ZIP en el subdirectorio `backups` del punto de montaje de `${project}_clickhouse-data-v26-2`. Una vez creado, cópialo a `$cut_dir` y compara su SHA-256 con el original. Para archivar volúmenes detenidos usa su punto de montaje verificado por Docker y `tar --numeric-owner --acls --xattrs`. Guarda en `$cut_dir` los tamaños, los SHA-256 del ZIP, `postgres.dmp`, `postgres-globals.sql` y los archivos auxiliares, junto con el ID, la hora UTC y el alcance de la captura. Ante `BACKUP_FAILED` o falta de verificación, conserva los escritores detenidos mientras se decide si reintentar o reabrir con 4.5.4. Las contraseñas, ACL de operación y el restablecimiento de replicación requieren verificación en la recuperación coordinada.

## Drenaje y reapertura

1. **Pausar las colas y coordinar productores**. Registra hora, entradas API/webhook, CI, deploy-agent y cron. Los schedules declarativos se reconcilian por sus ocurrencias UTC. La pausa de un entorno evita nuevos dequeues mientras deja continuar los runs iniciados. Los cron y llamadas API todavía pueden generar backlog. En 4.5.4 la pausa se controla en **Queues** por proyecto y entorno. Conserva el estado previo de cada pausa. [Pausa en 4.5.4](https://github.com/triggerdotdev/trigger.dev/blob/v4.5.4/apps/webapp/app/v3/services/pauseEnvironment.server.ts) · [Scheduler 4.5.4](https://github.com/triggerdotdev/trigger.dev/blob/v4.5.4/internal-packages/schedule-engine/src/engine/index.ts)
2. **Dejar terminar cadenas activas**. Contrasta el panel Runs y los logs del Supervisor en dos observaciones. Revisa `DEQUEUED`, `EXECUTING`, `WAITING_TO_RESUME` y `RETRYING_AFTER_FAILURE`, incluidos los runs anteriores al día. Identifica los waits/checkpoints y el backlog retenido por entorno. Si una cadena sigue activa al llegar al límite acordado, decide su reanudación antes del DDL. Un runner idle del broker puede seguir visible aunque el entorno esté drenado.
3. **Fijar la frontera**. Con las colas pausadas y las cadenas resueltas, registra backlog y cron pendientes. Comprueba RabbitMQ mediante `rabbitmqctl list_queues -p / name messages_ready messages_unacknowledged consumers`. Detén Supervisor y los escritores, incluidos Webapp y Electric en el orden que permita capturar el watermark de replicación. Si se usa la parada selectiva, Webapp y el agente de despliegue cierran sus entradas al detenerse. En el recurso Webapp, identifica y detén los contenedores individuales por etiqueta para mantener PostgreSQL y ClickHouse activos para sus backups y ClickHouse para Goose. Comprueba los clientes que puedan escribir a PostgreSQL por el proxy `:5432`. Detén o quiesce los auxiliares según el artefacto. Registra la hora UTC común y verifica el punto de recuperación antes del DDL. [Sonda de RabbitMQ](https://www.rabbitmq.com/docs/man/rabbitmqctl.8#list_queues)
4. **Migrar en el orden probado**. Deja ClickHouse accesible en la red del recurso, con los escritores anteriores detenidos. Aplica Goose con la imagen 4.8.3 hasta `044` y comprueba atributos. Luego avanza hasta `055` y ejecuta [el procedimiento de Search v2](#backfill-de-search-v2). Tras `045` y `046`, una vuelta a Webapp 4.5.4 exige restaurar los datos compatibles. Después de verificar `056` despliega Webapp y luego Supervisor desde sus recursos Coolify. [Ensayo y reversión](actualizacion-4.8.3.md#recuperación)
5. **Canario aislado**. Mantén cerradas las entradas ordinarias y los demás entornos pausados. Usa un proyecto `staging` acordado, sin backlog, cron ni efectos externos, que use el mismo worker. Mantén acceso a la API y `/otel` para Supervisor, runners, agente y operador durante el mantenimiento. Tras cambiar el agente a `TRIGGER_CLI_VERSION=4.8.3`, permite un único job y registra la versión desplegada. Si usas la CLI directa, `npx trigger.dev@4.8.3 deploy --env staging --skip-promotion` deja la promoción para después. Selecciona la versión explícitamente en el panel o en el SDK y comprueba el deployment del run. Valida registry, cold/warm, Sessions y trazas. [CLI y despliegue atómico](https://trigger.dev/docs/deployment/atomic-deployment)
6. **Reabrir**. Restaura los estados previos de las pausas y habilita las entradas por grupos. Reconcilia backlog, cron y entregas por IDs o claves de idempotencia. Contrasta colas, error rate y latencia con el baseline. [Matriz de aceptación](actualizacion-4.8.3.md#matriz-de-aceptación)

A las 11:43 CET del 13 de noviembre, la lectura del recurso `sk040488wkgwcgo84w8k4gks` de TriggerEU confirmó que los cinco entornos con despliegues promovidos estaban pausados. Son Fibra en producción y staging, y Fibra - Brainet, Orange y Orange - Brainet en staging. Quedaron cuatro runs programados de Fibra en `PENDING`, dos en producción y dos en staging. La lectura devolvió cero runs en ejecución, en espera de reanudación o en reintento. Los dos `DEQUEUED` de staging databan de marzo. `deploy_queue` registró cero listos y cero sin confirmar en la lectura previa. Repite las sondas al cerrar entradas y antes de detener los escritores.

A las 11:57 CET se verificó la parada manual en Coolify de `trigger-worker1`, `trigger-deploy-agent` y `trigger-warm-broker`. PostgreSQL conservaba cero runs activos. Quedó un contenedor de runner cuyo run de staging ya había finalizado correctamente. Los volúmenes del agente y de RabbitMQ seguían presentes. El Cloud Volume tenía 96,6 GiB disponibles. PostgreSQL y ClickHouse seguían activos, con ClickHouse en Goose `35`.

La parada selectiva terminó a las **12:04:40 CET (11:04:40 UTC)**. Se detuvo el runner residual y no quedaron runners activos. En `Tn-Trigger` se detuvieron el proxy de PostgreSQL, Webapp, Electric, S2, MinIO y Redis. Redis guardó su RDB y `redis-check-rdb` lo validó antes de la parada. Webapp agotó los 45 segundos de espera de Docker y terminó con código `137`, sin OOM. La API de TriggerEU y la entrada de despliegues devolvieron HTTP `503`, y el puerto `5432` quedó sin listener.

PostgreSQL `16.15` y ClickHouse `26.2.19.43` quedaron sanos, con cero sesiones de cliente adicionales en PostgreSQL al cierre y Goose en `35`. Los slots `electric_slot_default` y `task_runs_to_clickhouse_v1` quedaron inactivos con `restart_lsn=5B/E4852EC0` y `confirmed_flush_lsn=5B/E4852EF9`. Los 21 runs de la muestra, actualizados en la última media hora y creados desde el 6 de noviembre, coincidieron en ID, entorno, estado y hora de actualización entre PostgreSQL y ClickHouse.

### Respaldo del corte del 13 de noviembre

La captura del corte quedó verificada a las **12:31:45 CET (11:31:45 UTC)** en `Tn-Trigger`, bajo `/mnt/HC_Volume_107434992/trigger-eu-rollback/trigger-cut-20261113T111348Z`. `recovery-point-verified.utc` registra el cierre de la verificación y `SHA256SUMS` cubre 39 archivos, entre ellos el manifiesto de la copia física, el dump, el ZIP, los archivos auxiliares y las recetas efectivas anteriores de Webapp, Supervisor, agente y broker. Para recuperar credenciales, usa las variables de los recursos de Coolify. Los escritores siguieron detenidos durante la captura. Al cierre, PostgreSQL tenía 795 migraciones Prisma aplicadas y cero sin terminar, los slots conservaban la posición registrada al detener los escritores y ClickHouse seguía en Goose `35`.

| Artefacto | Tamaño y comprobación |
| --- | --- |
| PostgreSQL físico | `base/`, **51,83 GiB**. Copiado en **11 min 06 s** a un máximo de 80 MiB/s, con WAL en streaming y manifiesto SHA-256. `pg_verifybackup` verificó los archivos y el WAL en **6 min 21 s** desde un contenedor sin red con montaje de solo lectura. |
| PostgreSQL lógico | `postgres.dmp`, **4,54 GiB**. Se leyeron las 682 entradas del TOC y se decodificó el archivo completo con `pg_restore --file=/dev/null`. Se guardaron metadatos globales, publicaciones y posiciones de replicación. |
| ClickHouse | `clickhouse.zip`, **0,87 GiB**, con `trigger_dev` y el journal Goose. `BACKUP_CREATED`, SHA-256 igual al original y comprobación CRC de 212.870 entradas. El volumen de origen conserva el marcador `fresh`. Las fusiones TTL de raw v2 y Search v1 quedaron pausadas para el backfill. |
| Auxiliares | Ocho archivos comprimidos, **0,80 GiB**. Redis, S2 datos y configuración, MinIO datos y certificados, bootstrap compartido, workspace del agente y RabbitMQ. Los archivos se leyeron completos y el RDB archivado coincide por SHA-256 con el RDB del corte. |

La prueba de arranque de PostgreSQL y la restauración completa de ambas bases corresponden al ensayo del 11 de noviembre. A las **12:39:11 CET (11:39:11 UTC)**, tras volver a comprobar los 39 archivos del corte por SHA-256, se retiró únicamente `20261111T133752Z/base`. Se recuperaron **51,81 GiB** y el Cloud Volume quedó con **90,37 GiB libres**. Preparar una copia de trabajo de `trigger-cut-20261113T111348Z/base` dejaría unos **38,54 GiB** para los archivos de recuperación y WAL adicional. Conserva intacto el directorio del corte.

### Canario acordado

El canario acordado es **Fibra → Staging → `hello-world`**. El 11 de noviembre, el despliegue `current` de ese entorno era `20261103.5` con CLI y SDK `4.5.4`, proyecto `proj_tgaeqppbuwskratyvwwu` y commit `6eff19cdc9a48871a6b14f6e715583ab0857fbc1` de `trigger-simple`. En ese commit `src/trigger/index.ts` exporta la tarea de `src/trigger/example.ts`. Lánzala con `{}` y confirma `COMPLETED_SUCCESSFULLY`, el mensaje `Hello, world!` en los logs y el resultado `{"message":"Hello, world!"}` tras la espera de cinco segundos. Registra la versión realmente ejecutada. Para validar el despliegue con 4.8.3, repite la comprobación con la nueva versión seleccionada explícitamente.

El 13 de noviembre, `current` pasó a `20261112.1` (CLI y SDK `4.5.4`, commit `12618d7ce44090cd3bc5373e0e943ca53bbd54a7`). El índice sigue incluyendo `hello-world` sin esquema de payload. Para probar el código ya revisado, selecciona explícitamente `20261103.5`, que sigue registrada como `DEPLOYED` con imagen referenciada. Comprueba que el registry sirve la imagen antes del canario.

### Cierre temporal de entradas

Para la captura se puede cerrar la API y la entrada de despliegues deteniendo sus contenedores de forma selectiva tras el drenaje. Comprueba que las rutas dejan de aceptar peticiones y que no quedan escritores por vías internas. Al desplegar Webapp, su ruta vuelve a estar disponible. Mantén coordinadas las pausas de productores durante el canario. La configuración de Traefik de abajo permite restringir el acceso también mientras Webapp está en marcha.

En `.15`, Traefik observa `/data/coolify/proxy/dynamic` y `services-security.yaml` ya usa routers con `ipAllowList`. Durante la ventana, usa un archivo temporal con reglas `Host` para `trigger.sidicom.es` y `trigger-deploy.sidicom.es`. Da prioridad sobre las rutas ordinarias al servicio `noop@file` sin servidores, que devuelve `503`. Durante el drenaje y el canario, configura una ruta de prioridad superior hacia el `@docker` efectivo, con las opciones TLS y los middlewares del recurso. Limita el acceso a los orígenes necesarios en cada fase y dominio. Mantén la ruta de `503` durante las recreaciones para cubrir un cambio de nombre del servicio. Verifica el cierre o la redirección en HTTP, el rechazo desde un origen ordinario en HTTPS y las sondas de API y OTLP desde los orígenes autorizados. Retira el archivo temporal al reabrir y verifica las rutas originales. [Prioridad de rutas](https://doc.traefik.io/traefik/reference/routing-configuration/http/routing/rules-and-priority/) · [Lista de IP](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/ipallowlist/) · [Servicio de mantenimiento](https://doc.traefik.io/traefik/getting-started/faq/#xxx-instead-of-404)

Las sondas de Traefik vieron al Supervisor como `10.21.30.16`, al host `.15` como `10.21.30.15` y al agente a través de la IP NAT `172.24.0.1`. Verifica el origen de un runner y del operador antes de permitirlos. Si se admite la IP NAT del agente, comprueba que las entradas ordinarias que compartan ese origen estén pausadas. Las conexiones SSE o WebSocket abiertas pueden continuar después de recargar rutas. Detén los escritores tras el drenaje antes de capturar las bases.

Comprueba si hay consumidores del PostgreSQL publicado y coordina su pausa. Durante la captura detén por separado el proxy de Coolify `fc4ws4sogks04c84w8ow8sks` para fijar la frontera de escrituras. Las conexiones internas usan el alias de Compose. Comprueba el cierre y vuelve a habilitar el proxy al reabrir.

## Backfill de Search v2

Descarga la imagen fijada de Webapp 4.8.3 en Tn-Trigger antes de ejecutar Goose y el mapper de Search v2. La descarga puede hacerse mientras TriggerEU está en servicio. Coolify descarga la imagen del Supervisor cuando se despliega su receta. Con la Webapp anterior detenida y el punto de recuperación verificado, ejecuta Goose sobre el Compose generado, la `.env` de Coolify y un override privado de la imagen. Mantén las variables `project`, `ch`, `cut_id` y `cut_dir` del bloque de captura. Verifica que hay espacio para las tablas temporales, sus fusiones y la nueva proyección de búsqueda. [Comando probado en el clon](actualizacion-4.8.3.md#ensayo-de-preservación-de-atributos-y-búsqueda)

```bash
resource_dir="/data/coolify/services/$project"
cat > "$cut_dir/goose.override.yml" <<'YAML'
services:
  webapp:
    image: ghcr.io/triggerdotdev/trigger.dev:v4.8.3@sha256:54aa67fa90cd1fc88ce11ae670e6dbb8f12d2ba8b39e839e882d9e32bb8bdb1f
YAML

compose_cut() {
  docker compose --project-directory "$resource_dir" --env-file "$resource_dir/.env" \
    -p "$project" -f "$resource_dir/docker-compose.yml" -f "$cut_dir/goose.override.yml" "$@"
}

goose_cut() {
  compose_cut run --rm --no-deps -T --pull never --entrypoint /bin/sh webapp -ec '
    export GOOSE_DRIVER=clickhouse GOOSE_DBSTRING="$CLICKHOUSE_URL"
    export GOOSE_MIGRATION_DIR=/triggerdotdev/internal-packages/clickhouse/schema
    exec /usr/local/bin/goose "$@"
  ' sh "$@"
}

compose_cut config --quiet
goose_cut status
```

1. Comprueba que TTL sigue pausado en `task_events_v2` y `task_events_search_v1` antes de tomar las huellas de partida. Deja disponibles las fusiones ordinarias durante `042`. Ejecuta `goose_cut up-to 44`, comprueba cobertura de `attributes_text` por partes y compara los valores con el JSON original. Conserva la huella raw y la de Search v1 por fecha. Ejecuta `goose_cut up-to 55`, comprueba el journal y repite las huellas antes de seguir.
2. En `055`, conserva Search v1 y su vista. Pausa fusiones ordinarias y TTL en raw v2 y ambas tablas Search. Espera cero fusiones y mutaciones activas en las tres. Copia [el script](../scripts/search-v2-backfill.py) y [su mapper](../scripts/search-v2-mapper.cjs) juntos al directorio privado del corte. El archivo del mapper se monta en solo lectura y debe ser legible por el grupo `1000` del usuario `node` de la imagen fijada. Usa propietario `root`, grupo `1000` y modo `0640` para ese archivo. La base `stage_db` es exclusiva de ese corte. El script rechaza un contenedor, volumen, host, esquema o journal inesperado y comprueba las claves y el contenido por fecha de inserción.

   ```bash
   for table in task_events_v2 task_events_search_v1 task_events_search_v2; do
     docker exec "$ch" clickhouse-client -q "SYSTEM STOP TTL MERGES trigger_dev.$table"
     docker exec "$ch" clickhouse-client -q "SYSTEM STOP MERGES trigger_dev.$table"
   done

   stage_db="trigger_eu_search_stage_$(date -u +%Y%m%d_%H%M%S)"
   backfill() {
     python3 "$cut_dir/search-v2-backfill.py" "$1" --profile trigger-eu --container "$ch" \
       --stage-db "$stage_db" --evidence-dir "$cut_dir/search-evidence" --confirm-merges-frozen
   }

   backfill stage
   backfill apply
   backfill apply   # Comprueba que esta segunda ejecución inserta cero filas.
   backfill verify
   ```

3. Antes de `056`, exige cero conflictos y cero claves faltantes. Comprueba muestras con búsquedas de palabra y subcadena y resultados ordenados, incluidas trazas antiguas. Aplica `goose_cut up-to 56`, ejecuta `backfill verify` otra vez y compara las mismas muestras. Guarda los informes de aplicación, repetición y verificación en `055` y `056` con el manifiesto. Si un paso falla, guarda su evidencia antes de reintentar. Tras validar, elimina la base temporal de ese corte con `DROP DATABASE <stage_db> SYNC` antes de reabrir. Devuelve las fusiones ordinarias y TTL de `task_events_v2` y `task_events_search_v2` a su estado operativo con `SYSTEM START MERGES` y `SYSTEM START TTL MERGES`, respectivamente. Los datos que superan 90 días siguen sujetos a retención. El ZIP mantiene el histórico original.

El script versionado se probó en un contenedor aislado con ClickHouse `26.2.19.43` autenticado y la imagen 4.8.3 fijada. Cubrió un registro exclusivo de Search v1, un evento raw excluido, dos días, una colisión rechazada y búsquedas de texto, subcadena y errores. La primera pasada insertó cuatro filas, la repetición insertó cero y las huellas coincidieron tras `056`. [Ensayo anterior con datos representativos](actualizacion-4.8.3.md#ensayo-con-copias-de-producción)

### Migraciones `036` a `044` en TriggerEU

El 13 de noviembre, Goose aplicó las nueve migraciones de ClickHouse de `036` a `044` entre las **12:50:27 y las 12:50:45 CET**. Se usó un contenedor temporal de la imagen fijada de Webapp 4.8.3. La verificación terminó a las **12:52:05 CET** y el journal registró `044`, con cero mutaciones pendientes. La consulta auxiliar del primer intento usó una columna inexistente en el journal. Se corrigió el orden a `version_id`, `tstamp` e `is_applied` antes de ejecutar Goose y se reutilizaron las huellas previas.

Coincidieron los conteos y las huellas por día de **8.775.817 eventos raw en 114 días** y **3.718.195 filas de Search v1 en 91 días**. Las 229 partes activas de raw registraron `attributes_text` y las 8.775.817 filas coincidieron con `toJSONString(attributes)`. La columna pasó a `DEFAULT toJSONString(attributes)`. Search v1 y su vista conservaron sus definiciones. Search v2 quedó creada y vacía. Los informes y las huellas están en `trigger-cut-20261113T111348Z/goose-044` del volumen de Hetzner.

### Migraciones `045` a `055` y backfill en TriggerEU

Goose aplicó las once migraciones de `045` a `055` entre las **12:57:37 y las 12:57:51 CET** del 13 de noviembre. Las huellas por día de raw y Search v1 coincidieron con las de `044` tras retirar las columnas JSON `attributes` y `attributes_input`. Se conservó `attributes_text` y las definiciones de Search v1 y su vista. Las fusiones ordinarias y TTL de raw y de ambas tablas Search quedaron pausadas para verificar la copia.

El primer intento de staging se detuvo porque el usuario `node` de la imagen no podía leer el mapper. Se ajustó el permiso del archivo, se comprobó su arranque en la imagen fijada y se reanudó en `trigger_eu_search_stage_20261113_111348_retry1`. La base inicial `trigger_eu_search_stage_20261113_111348` quedó vacía. Conserva el staging con datos hasta repetir las verificaciones tras `056` y retira ambas bases temporales al finalizar esa fase.

La carga insertó **4.618.147 proyecciones únicas en 114 días**. Incluyen las **3.718.195** de Search v1 y **899.952** adicionales procedentes de raw. El mapper oficial ajustó la marca de tiempo de 1.903 proyecciones de Search v1. La segunda aplicación insertó cero filas. La verificación confirmó cero conflictos, claves faltantes o filas ajenas al origen. Nueve consultas de lista, palabra y subcadena devolvieron 100 filas cada una con el mismo contenido y orden que el staging para el 23 de julio, el 16 de agosto y el 13 de noviembre.

La verificación cerró a las **13:16:36 CET** con Goose en `055`. Los informes, la referencia de las búsquedas y `evidence-055.sha256` quedaron en `trigger-cut-20261113T111348Z/goose-055` del volumen de Hetzner. Al cierre, unas **930.000** proyecciones de Search v2, entre ellas **29.658** procedentes de Search v1, ya superaban la edad de retención de 90 días. El TTL sigue pausado y el ZIP del corte conserva los datos originales.

### Migración `056` en TriggerEU

Goose aplicó `056` a las **13:26:00 CET** del 13 de noviembre y retiró `task_events_search_v1` y `task_events_search_mv_v1`. Antes del cambio se comprobó el SHA-256 del ZIP del corte. A las **13:27:41 CET** quedaron verificados el journal, los **8.775.817 eventos raw** y las huellas por día de las **4.618.147 proyecciones de Search v2 en 114 días**. Las nueve consultas de lista, palabra y subcadena repitieron exactamente el contenido y el orden observados en `055`. La evidencia está en `trigger-cut-20261113T111348Z/goose-056` del volumen de Hetzner.

La lectura al cierre encontró cero fusiones activas y cero mutaciones pendientes en raw y Search v2. Las dos bases temporales quedan disponibles para la comprobación del despliegue y se retiran antes de reabrir el tráfico. La pausa de fusiones es local al proceso de ClickHouse. Si Coolify lo recrea, se aplicará de nuevo la retención de sus tablas. El ZIP del corte conserva los datos originales. [Fusiones de MergeTree](https://clickhouse.com/docs/reference/statements/system#system-stop-merges)

### Despliegue de Webapp en Coolify

En `teamnet-trigger-eu / production`, abre el recurso existente `sk040488wkgwcgo84w8k4gks` de `Tn-Trigger`. En **Configuration → General → Edit Compose File**, aplica estos cambios sobre el **Source Compose** efectivo. Conserva las demás entradas del bloque `environment` de Webapp, las variables de Coolify, los dominios y los nombres de servicios y volúmenes. [Edición de Compose en Coolify](https://coolify.io/docs/services/configuration/docker-compose)

```yaml
# Valores a incorporar a los bloques existentes
services:
  webapp:
    image: 'ghcr.io/triggerdotdev/trigger.dev:v4.8.3@sha256:54aa67fa90cd1fc88ce11ae670e6dbb8f12d2ba8b39e839e882d9e32bb8bdb1f'
    environment:
      - 'EVENT_REPOSITORY_V1_REROUTE_ENABLED=${EVENT_REPOSITORY_V1_REROUTE_ENABLED:-0}'
      - 'LOGS_SEARCH_DUAL_WRITE_ACTIVE=${LOGS_SEARCH_DUAL_WRITE_ACTIVE:-on}'
      - TRIGGER_CLI_TAG=4.8.3
  postgres:
    image: 'postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
  redis:
    image: 'redis:7@sha256:c6eabf748fc7a61dbb5a705c78bcf3d6377b1127a97d0ce965c11c44ba46896f'
  minio:
    image: 'bitnamilegacy/minio:latest@sha256:451fe6858cb770cc9d0e77ba811ce287420f781c7c1b806a386f6896471a349c'
```

Los tres digests de dependencias corresponden a las imágenes efectivas del corte. Se validó el delta contra el Compose generado. Revisa el **Deployable Compose** y confirma `CLICKHOUSE_STORAGE_INIT_MODE=fresh`, el volumen `clickhouse-data-v26-2`, `EVENT_REPOSITORY_DEFAULT_STORE=clickhouse_v2` y `RUN_REPLICATION_ENABLED=1`. Guarda y despliega ese recurso desde Coolify. Verifica Webapp, sus dependencias y los journals antes de desplegar el Worker. Mantén pausadas las colas para el canario de Fibra en staging.

### Validación de Webapp tras el despliegue

Webapp `4.8.3` arrancó en Coolify a las **13:39:03 CET** del 13 de noviembre, con el digest de la receta y el volumen compartido existente. `/healthcheck` devolvió `200` desde ambos hosts y desde el contenedor. La raíz devolvió `302`, y Sessions y Realtime devolvieron `401` JSON en las sondas sin credenciales. Electric, S2 y MinIO respondieron `200`. S2 y MinIO también respondieron desde `Tn-Trigger-Worker1`. Se comprobaron los mismos servicios y volúmenes y las 22 entradas de configuración de producción contrastadas con el Compose del corte.

PostgreSQL pasó de `16.15` a `16.16` (digest `sha256:f377d590e5474681d4d7838635031a2b50647923b7abfa803ce9b5ff35d5c663`) y Redis de `7.4.11` a `7.4.12` (digest `sha256:2e3eb11462c4e3759e6972678dd051d150ff54b1e60714b3c33b701260172a90`). El despliegue resolvió las etiquetas móviles a esas imágenes. Ambos servicios quedaron sanos. Redis cargó el RDB. PostgreSQL registró **856** migraciones Prisma aplicadas, cero sin terminar, **9** de Drizzle y cero índices inválidos. Los slots de Electric y de replicación de runs estaban activos. El proxy TCP de PostgreSQL seguía detenido.

ClickHouse `26.2.19.43` reutilizó `clickhouse-data-v26-2` con el marcador `fresh` y registró Goose `056`. Al recrear el contenedor se reanudó el TTL. Search v2 conservó las **3.718.195** proyecciones procedentes de Search v1, con las mismas huellas en 91 días. El TTL retiró **899.952** proyecciones exclusivas de raw, de 23 particiones entre el 23 de julio y el 14 de agosto, todas vencidas al arrancar ClickHouse. Se conservan en el respaldo del corte. Queda por validar el indexado de logs nuevos con el canario.

La validación de Webapp cerró a las **13:51 CET**. Las cinco colas acordadas seguían pausadas y las seis ejecuciones observadas desde el arranque estaban pendientes en entornos pausados. El registro de SimpleTV Staging en TriggerEU tenía cuatro runs antiguos en estados no terminales, sin nuevas ejecuciones ni miembros en las colas listas de su entorno en Redis. El Worker, el broker y el agente seguían detenidos. El último Compose materializado del Worker en el host aún indicaba `4.5.4`. Despliega el Worker desde el recurso Git configurado en Coolify para materializar la receta candidata y comprobar después que el Supervisor arrancó en `4.8.3`.

### Arranque del warm-start broker en Coolify

Usa el recurso existente `trigger-warm-broker` (`ccem9d0rxqlcc2v8kzvkrob8`) con el broker `0.1.0` del commit `4873fe0` y el backend Redis de TriggerEU. La compatibilidad del protocolo con Supervisor `4.8.3` está documentada en el plan. Antes de arrancar, revisa **Custom Start Command** en Coolify. El Compose base resuelve `warm-start-broker:local`, que no existe en `Tn-Trigger`. El comando con el overlay resuelve `warm-start-broker:coolify-build`, que sí existe y corresponde al ID verificado `sha256:36139433d0bc9382cf7385a80f58f049fa72311a04715e1f77ed5b323c3813f4`.

```bash
docker compose -f docker-compose.yml -f docker-compose.build.example.yml up --no-build -d
```

Con ese comando, `WARM_START_BROKER_IMAGE` puede quedar vacía. Si el arranque usa el Compose base, la variable `WARM_START_BROKER_IMAGE=warm-start-broker:coolify-build` selecciona esa misma imagen local. En ese caso, confirma que el flujo de arranque reutiliza la imagen local. Un redespliegue desde Git puede volver a ejecutar la fase de build. Si la ejecuta, confirma que el checkout sea `4873fe0`. Tras arrancar, comprueba el ID de la imagen, la conexión con Redis y `/healthz` local y por HTTPS desde el Worker. [Operaciones de aplicaciones de Coolify](https://coolify.io/docs/applications/operations/overview)

Coolify reconstruyó el broker `0.1.0` y lo arrancó a las **14:30:23 CET** del 13 de noviembre. El tag `warm-start-broker:coolify-build` apunta ahora a `sha256:33f3af9273a12d6734f2858af0057f4cbbfc55b5de162ac4305fe26df19be59f`. Los SHA-256 de `src/broker.js` y `src/index.js` coinciden con los del commit `4873fe0`. A las **14:34 CET**, el contenedor estaba sano y `/healthz` devolvía `200` tanto en local como desde el host del Worker. El broker confirmó conexión al Redis de TriggerEU. Las cinco colas acordadas seguían pausadas y el Worker permanecía detenido. El canario comprobará la entrega real a un runner.

### Validación del Supervisor tras el despliegue

`trigger-worker1` arrancó a las **14:37:40 CET** del 13 de noviembre desde `e46bff5`, con Supervisor `4.8.3` `linux/amd64` y el digest de la receta `sha256:60808dded07c856481bd94ac0b6c64637dea828e57e918ca3ca270813feac74b`. Supervisor y `docker-proxy` quedaron sanos y sin reinicios. PostgreSQL registró una nueva instancia en el grupo `bootstrap` a las **14:37:43 CET** y seguía recibiendo sus heartbeats a las **14:48 CET**. Desde el contenedor, Supervisor, Docker `/_ping`, Webapp, el broker, S2 y MinIO devolvieron `200`. Las URL de registro y dispatch de warm starts resuelven al broker de TriggerEU. El endpoint OTLP apunta a `/otel` en la Webapp.

El registry HTTPS aceptó las credenciales del Supervisor y devolvió el manifiesto de Fibra Staging `20261103.5` con el digest registrado en TriggerEU. El daemon admite el endpoint privado `10.21.30.14:5000`. Queda por comprobar la descarga efectiva de la imagen y la ejecución del runner. No había runners activos durante la validación.

Los cinco entornos acordados seguían pausados. Fibra Staging tenía **33 runs pendientes**, 12 en `task/cron-update-failed-SAPs-scheduled` y 21 en `task/send-queue-scheduled`. También figuraba activo el schedule de `task/sap-listener-scheduled`. El test del panel respeta la pausa del entorno. Para ejecutar `hello-world` en ese entorno, pausa individualmente esas tres colas, confirma que no hay otro trabajo listo y mantén detenidos los productores ordinarios durante la reanudación de Fibra Staging. Ejecuta el test con `{}` y la versión `20261103.5` seleccionada, y vuelve a pausar el entorno tras la prueba. Registra los cambios de pausa por cola para restaurarlos al reabrir.

### Coste por run antes del canario

La receta de `coolify-trigger-ha` pasa `CENTS_PER_RUN` a Webapp y sus ejemplos usan `0`. El Compose efectivo de TriggerEU y el contenedor 4.8.3 no declaraban esa variable en la revisión del 13 de noviembre; Webapp ya usa `0` por defecto. En una muestra de los últimos 200 runs, los 129 completados con duración positiva tenían coste de cómputo y de invocación a cero.

Si se acuerda un cargo fijo, añade esta línea en **Source Compose → services → webapp → environment** del recurso `sk040488wkgwcgo84w8k4gks`, conservando el resto del Compose efectivo:

```yaml
      - 'CENTS_PER_RUN=${CENTS_PER_RUN:-0}'
```

En **Environment Variables** del mismo recurso, fija `CENTS_PER_RUN` en centavos de USD por invocación. El ejemplo de HA `0.0025` equivale a `USD 0.000025` por run. Usa el importe acordado para TriggerEU; `0` mantiene el comportamiento actual y no justifica recrear Webapp durante el corte. Con un importe distinto de cero, comprueba el valor que recibe el servicio en el **Deployable Compose**, recrea Webapp durante la ventana y verifica `/healthcheck` y el valor efectivo de la variable. El cambio de configuración corresponde a Webapp. Si se usa **Redeploy** del recurso completo, Coolify también puede recrear sus dependencias, así que revisa las imágenes efectivas y conserva los volúmenes del corte. [Source Compose y Deployable Compose en Coolify](https://coolify.io/docs/services/configuration/docker-compose)

Webapp guarda el importe en `baseCostInCents` al asignar un run al worker. Abarca toda la instancia y puede aplicarse a runs que ya estaban pendientes de su primera asignación. Los runs completados conservan sus importes. La imagen oficial observada tiene la tarifa de cómputo a cero en todos los presets. Con solo cargo fijo, el detalle del run muestra **Run invocation cost**; **Compute** y **Total cost** del detalle siguen mostrando un guion si `costInCents` es cero. En **Query** el total sí suma los dos importes.

Tras el canario de Fibra Staging, filtra por su ID público en **Query** con un rango que incluya el run. Comprueba que `invocation_cost` coincide con `CENTS_PER_RUN / 100` y que la réplica muestra el run completado antes de reabrir:

```sql
SELECT run_id, status, invocation_cost, compute_cost, total_cost
FROM runs
WHERE run_id = 'run_ID_DEL_CANARIO'
LIMIT 1
```

Para retirar el cargo, fija `CENTS_PER_RUN=0` y vuelve a recrear Webapp; el cambio se aplica a los siguientes runs al asignarse. Este ajuste de configuración no requiere migraciones ni backfill.

### Validación del redespliegue con coste por run

El 13 de noviembre a las **15:08:35 CET**, Coolify recreó Webapp y los servicios del recurso. Webapp `4.8.3` quedó sana con el mismo digest, cero reinicios y `CENTS_PER_RUN=0.03867` efectivo (**USD 0.0003867 por invocación**). El Supervisor `4.8.3` conservó su contenedor y volvió a registrar heartbeats en el grupo `bootstrap`. Webapp, Docker `/_ping`, el broker y MinIO respondieron `200` desde Supervisor; S2 devolvió el `404` esperado en la sonda HTTP a `/v1`. Sessions y Realtime mantuvieron sus respuestas `401` JSON sin credenciales. Webapp recurrió al RBAC integrado al fallar la carga del plugin opcional.

PostgreSQL y Redis conservaron sus digests anteriores, Redis cargó el RDB y ClickHouse conservó el volumen `clickhouse-data-v26-2`, el marcador `fresh` y Goose `056`. Prisma registró 856 migraciones aplicadas y ninguna incompleta. Los slots de Electric y de runs estaban activos. Un run de Fibra Staging en `PENDING` creado a las **15:15 CET** apareció con el mismo estado y marca de actualización en PostgreSQL y `task_runs_v2`. Queda por verificar el coste y los logs de un run ejecutado.

Los cinco entornos seguían pausados en PostgreSQL y con límite cero en Redis. A las **15:13 CET**, Fibra Staging tenía **41 runs pendientes** en las dos colas ya identificadas; los schedules siguen añadiendo trabajo mientras el entorno está pausado. Las tres colas programadas observadas todavía no estaban pausadas individualmente. La versión `20261103.5` seguía desplegada e incluía `hello-world`. Antes de habilitar temporalmente Fibra Staging, aísla esas tres colas y vuelve a revisar si hay otra tarea lista o productores activos. El canario y la reapertura siguen pendientes.

### Resultado del canario de Fibra Staging

El 13 de noviembre entre las **15:19 y las 15:21 CET**, el usuario ejecutó dos pruebas de `hello-world` con el despliegue `20261112.1`, que usa CLI y SDK `4.5.4`. Las dos terminaron en `COMPLETED_SUCCESSFULLY` al primer intento en Supervisor `4.8.3` y devolvieron `{"message":"Hello, world!"}`. El run `run_cmwf2cxe5000c3impvvf8y8hg` arrancó en frío y `run_cmwf2dcpw000l3impqqz4lo9h` usó warm start. Se verificó el log `Hello, world!` de ambos por ID de traza en `task_events_v2` y `task_events_search_v2`. PostgreSQL y `task_runs_v2` coincidieron en estado y coste. Cada run registró `baseCostInCents=0.03867`, `costInCents=0` y un total de **USD 0.0003867**. La prueba cubrió un despliegue ya existente. El flujo de publicar una versión con CLI y SDK `4.8.3` se valida aparte.

A las **15:24 CET**, Fibra Staging seguía reanudado. No se observaron runs ordinarios iniciados desde su reanudación a las **15:19 CET**. Las colas de `cron-update-failed-SAPs-scheduled` y `send-queue-scheduled` seguían pausadas, con 15 y 27 runs pendientes respectivamente. `sap-listener-scheduled` seguía habilitada y no tenía pendientes. Los otros cuatro entornos conservaban su pausa en PostgreSQL y Redis.

### Validación de la reapertura

El 13 de noviembre entre las **15:32 y las 15:36 CET**, los cinco entornos estaban habilitados en PostgreSQL y Redis, sin colas marcadas como pausadas. En la muestra de runs ordinarios iniciados desde las **15:24 CET** se registraron **141 éxitos** (45 en Fibra Production, 90 en Fibra Staging y 6 en Fibra - Brainet Staging), sin fallos ni reintentos pendientes. Redis mostró cero en espera a las 15:34 en los cinco entornos. Un nuevo pendiente de Fibra Staging visto a las 15:35 ya había salido de la cola en la segunda lectura. En los tres entornos con ejecuciones completadas, un run de muestra coincidió entre PostgreSQL y ClickHouse en estado y coste (**USD 0.0003867**) y tenía logs en Search v2.

Quedaba un run de `brainet-assistant` en Fibra - Brainet Staging esperando una señal manual, con vencimiento a las **16:31 CET**. En Orange Staging, Redis conservaba un contador de dequeue para `sap-listener` (`run_cmrx617sd0brk3jqsqakjzofk`), creado el 23 de julio y aún `PENDING` en PostgreSQL, sin inicio ni cambios desde esa fecha. Es un pendiente histórico y su reconciliación queda aparte de la reapertura.

Webapp, Supervisor, broker, agente y RabbitMQ estaban sanos. Los slots de Electric y ClickHouse seguían activos. RabbitMQ mostró cero mensajes listos o sin confirmar en `deploy_queue` y un consumidor. El agente tenía `TRIGGER_CLI_VERSION=4.5.4`, por lo que sigue pendiente la prueba de publicación con CLI y SDK `4.8.3`. El proxy TCP externo de PostgreSQL seguía detenido.

## Cronómetro y decisión de ventana

| Tramo | Referencia observada | Medición del corte |
| --- | --- | --- |
| Drenaje | p95 reciente de runs inferior a 7 s en ambos entornos. Los waits y el backlog antiguos requieren decisión individual. | Hora de cierre, última ejecución iniciada y confirmación de Supervisor drenado. |
| Capturas | Backup físico PostgreSQL **44 min 14 s** a 20 MiB/s y verificación **5 min 37 s**. Dump diario anterior en unos 10 min y ZIP ClickHouse en unos 3 min. | **17 min 57 s** desde el inicio de la captura hasta verificar los archivos en Hetzner. **27 min 05 s** desde la parada de los escritores. |
| ClickHouse | Aplicación y comparación del backfill en 4 min 38 s, además de staging, huellas y sondas. | `044` a las 12:50:45 CET, `055` a las 12:57:51 CET y `056` a las 13:26:00 CET. La carga y comparación por día tardaron **4 min 42 s** y la verificación final cerró a las 13:27:41 CET. |
| Webapp y canarios | Prisma y Drizzle en 7 s sobre copia real. El arranque Coolify, la descarga de imágenes y los canarios de aplicación se miden aparte. | Webapp sana desde el despliegue de las 13:39 CET. Supervisor registrado a las 14:37:43 CET. Queda pendiente la ejecución del canario. |
| Recuperación | PostgreSQL físico en Tn-Trigger **22 min 13 s** para preparar la copia de trabajo y **703 ms** hasta la primera consulta. Restauración lógica PostgreSQL **1 h 43 min 27 s** en el SSD y ClickHouse **55 s** desde el directorio ya expandido. | Tiempo aprobado para restaurar y reconciliar ambos motores, replicación y auxiliares en el almacenamiento de recuperación. |

Antes de fijar el inicio, acuerda la hora de comienzo y fin, el responsable de rollback y la ruta de recuperación. Calcula el punto de decisión desde el fin de la ventana menos el tiempo de restauración y verificación que se acepte. La duración de las migraciones del clon sirve para planificar el cambio de versión. La capacidad de recuperar el servicio se verifica con el conjunto del corte y la reconciliación posterior.
