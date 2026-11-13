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

1. **Cerrar productores**. Registra hora, entradas API/webhook, CI, deploy-agent y cron. Los schedules declarativos se reconcilian por sus ocurrencias UTC. La pausa de un entorno evita nuevos dequeues mientras deja continuar los runs iniciados. Los cron y llamadas API todavía pueden generar backlog. En 4.5.4 la pausa se controla en **Queues** por proyecto y entorno. Conserva el estado previo de cada pausa. [Pausa en 4.5.4](https://github.com/triggerdotdev/trigger.dev/blob/v4.5.4/apps/webapp/app/v3/services/pauseEnvironment.server.ts) · [Scheduler 4.5.4](https://github.com/triggerdotdev/trigger.dev/blob/v4.5.4/internal-packages/schedule-engine/src/engine/index.ts)
2. **Dejar terminar cadenas activas**. Contrasta el panel Runs y los logs del Supervisor en dos observaciones. Revisa `DEQUEUED`, `EXECUTING`, `WAITING_TO_RESUME` y `RETRYING_AFTER_FAILURE`, incluidos los runs anteriores al día. Identifica los waits/checkpoints y el backlog retenido por entorno. Si una cadena sigue activa al llegar al límite acordado, decide su reanudación antes del DDL. Un runner idle del broker puede seguir visible aunque el entorno esté drenado.
3. **Fijar la frontera**. Con entradas ordinarias cerradas y las cadenas resueltas, pausa los entornos que usan el worker. Registra backlog y cron pendientes. Comprueba RabbitMQ mediante `rabbitmqctl list_queues -p / name messages_ready messages_unacknowledged consumers`. Detén Supervisor y los escritores, incluidos Webapp y Electric en el orden que permita capturar el watermark de replicación. En el recurso Webapp, identifica y detén los contenedores individuales por etiqueta si la acción de Coolify detiene el recurso entero. PostgreSQL y ClickHouse deben estar activos para sus backups y ClickHouse para Goose. Comprueba los clientes que puedan escribir a PostgreSQL por el proxy `:5432`. Detén o quiesce los auxiliares según el artefacto. Registra la hora UTC común y verifica el punto de recuperación antes del DDL. [Sonda de RabbitMQ](https://www.rabbitmq.com/docs/man/rabbitmqctl.8#list_queues)
4. **Migrar en el orden probado**. Deja ClickHouse accesible en la red del recurso, con los escritores anteriores detenidos. Aplica Goose con la imagen 4.8.3 hasta `044` y comprueba atributos. Luego avanza hasta `055` y ejecuta [el procedimiento de Search v2](#backfill-de-search-v2). Tras `045` y `046`, una vuelta a Webapp 4.5.4 exige restaurar los datos compatibles. Después de verificar `056` despliega Webapp y luego Supervisor desde sus recursos Coolify. [Ensayo y reversión](actualizacion-4.8.3.md#recuperación)
5. **Canario aislado**. Mantén cerradas las entradas ordinarias y los demás entornos pausados. Usa un proyecto `staging` acordado, sin backlog, cron ni efectos externos, que use el mismo worker. Mantén acceso a la API y `/otel` para Supervisor, runners, agente y operador durante el mantenimiento. Tras cambiar el agente a `TRIGGER_CLI_VERSION=4.8.3`, permite un único job y registra la versión desplegada. Si usas la CLI directa, `npx trigger.dev@4.8.3 deploy --env staging --skip-promotion` deja la promoción para después. Selecciona la versión explícitamente en el panel o en el SDK y comprueba el deployment del run. Valida registry, cold/warm, Sessions y trazas. [CLI y despliegue atómico](https://trigger.dev/docs/deployment/atomic-deployment)
6. **Reabrir**. Restaura los estados previos de las pausas y habilita las entradas por grupos. Reconcilia backlog, cron y entregas por IDs o claves de idempotencia. Contrasta colas, error rate y latencia con el baseline. [Matriz de aceptación](actualizacion-4.8.3.md#matriz-de-aceptación)

El canario acordado es **Fibra → Staging → `hello-world`**. El 11 de noviembre, el despliegue `current` de ese entorno era `20261103.5` con CLI y SDK `4.5.4`, proyecto `proj_tgaeqppbuwskratyvwwu` y commit `6eff19cdc9a48871a6b14f6e715583ab0857fbc1` de `trigger-simple`. En ese commit `src/trigger/index.ts` exporta la tarea de `src/trigger/example.ts`. Lánzala con `{}` y confirma `COMPLETED_SUCCESSFULLY`, el mensaje `Hello, world!` en los logs y el resultado `{"message":"Hello, world!"}` tras la espera de cinco segundos. Registra la versión realmente ejecutada. Para validar el despliegue con 4.8.3, repite la comprobación con la nueva versión seleccionada explícitamente.

El 13 de noviembre, `current` pasó a `20261112.1` (CLI y SDK `4.5.4`, commit `12618d7ce44090cd3bc5373e0e943ca53bbd54a7`). El índice sigue incluyendo `hello-world` sin esquema de payload. Para probar el código ya revisado, selecciona explícitamente `20261103.5`, que sigue registrada como `DEPLOYED` con imagen referenciada. Comprueba que el registry sirve la imagen antes del canario.

### Cierre temporal de entradas

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
2. En `055`, conserva Search v1 y su vista. Pausa fusiones ordinarias y TTL en raw v2 y ambas tablas Search. Espera cero fusiones y mutaciones activas en las tres. Copia [el script](../scripts/search-v2-backfill.py) y [su mapper](../scripts/search-v2-mapper.cjs) juntos al directorio privado del corte. La base `stage_db` es exclusiva de ese corte. El script rechaza un contenedor, volumen, host, esquema o journal inesperado y comprueba las claves y el contenido por fecha de inserción.

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

## Cronómetro y decisión de ventana

| Tramo | Referencia observada | Medición del corte |
| --- | --- | --- |
| Drenaje | p95 reciente de runs inferior a 7 s en ambos entornos. Los waits y el backlog antiguos requieren decisión individual. | Hora de cierre, última ejecución iniciada y confirmación de Supervisor drenado. |
| Capturas | Backup físico PostgreSQL **44 min 14 s** a 20 MiB/s y verificación **5 min 37 s**. Dump diario anterior en unos 10 min y ZIP ClickHouse en unos 3 min. | Tiempo desde la frontera hasta tener archivos y hashes verificados en el volumen de Hetzner. |
| ClickHouse | Aplicación y comparación del backfill en 4 min 38 s, además de staging, huellas y sondas. | Hora de `044`, `055`, cobertura y `056`. |
| Webapp y canarios | Prisma y Drizzle en 7 s sobre copia real. El arranque Coolify, la descarga de imágenes y los canarios de aplicación se miden aparte. | Webapp sana, Supervisor registrado, despliegue canario y comprobaciones. |
| Recuperación | PostgreSQL físico en Tn-Trigger **22 min 13 s** para preparar la copia de trabajo y **703 ms** hasta la primera consulta. Restauración lógica PostgreSQL **1 h 43 min 27 s** en el SSD y ClickHouse **55 s** desde el directorio ya expandido. | Tiempo aprobado para restaurar y reconciliar ambos motores, replicación y auxiliares en el almacenamiento de recuperación. |

Antes de fijar el inicio, acuerda la hora de comienzo y fin, el responsable de rollback y la ruta de recuperación. Calcula el punto de decisión desde el fin de la ventana menos el tiempo de restauración y verificación que se acepte. La duración de las migraciones del clon sirve para planificar el cambio de versión. La capacidad de recuperar el servicio se verifica con el conjunto del corte y la reconciliación posterior.
