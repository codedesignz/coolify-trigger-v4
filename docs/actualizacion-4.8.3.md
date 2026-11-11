# Actualización de TriggerEU Prod a Trigger.dev 4.8.3

El origen observado el 11 de noviembre de 2026 es `v4.5.4`. La ruta propuesta es directa a `v4.8.3` (commit upstream `645cc47dd2eeb99387f604cad2c90ba2ef568680`), con una ventana para los dos entornos de Trigger.dev porque comparten Webapp, datos y worker. El orden es preservación y migración de ClickHouse, Webapp, Supervisor y despliegue canario de tareas. [Release 4.8.3](https://github.com/triggerdotdev/trigger.dev/releases/tag/v4.8.3) · [Comparación 4.5.4 a 4.8.3](https://github.com/triggerdotdev/trigger.dev/compare/v4.5.4...v4.8.3)

## Recetas y artefactos

| Componente | Recurso de Coolify | Imagen candidata |
| --- | --- | --- |
| Webapp · `10.21.30.15` | `sk040488wkgwcgo84w8k4gks` | [`trigger.dev:v4.8.3`](../webapp/docker-compose.yml) |
| Supervisor · `10.21.30.16` | `trigger-worker1` · `z0wos4o0kg8osw40wc4kkkcg` | [`supervisor:v4.8.3`](../worker/docker-compose.yml) |
| Warm-start broker · `10.21.30.15` | `trigger-warm-broker` · `ccem9d0rxqlcc2v8kzvkrob8` | Reutilizar `0.1.0` (commit `4873fe0800ecdd8fdcbeb3e21b7c696ff7ac6ca4`), build local de Coolify con Redis |
| Agente de despliegue · `10.21.30.15` | `trigger-deploy-agent` · `xc000kcskwwosc00k0wcs8s0` | Pasar `TRIGGER_CLI_VERSION` de `4.4.4` a `4.8.3` en el mismo recurso. Conservar el build del agente, RabbitMQ y registry |

El inventario contiene rutas, volúmenes y puertos del origen. Los dos Compose fijan el índice multiarch. En cada host, registra la plataforma y contrasta el índice de GHCR, el manifiesto de esa plataforma y el ID efectivo de la imagen tras el despliegue. Usa `docker buildx imagetools inspect <imagen>` para el índice y `docker image inspect --format '{{.Id}} {{json .RepoDigests}}' <imagen>` para la imagen descargada. [Inventario](inventario.md) · [Compose oficial de Webapp](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/hosting/docker/webapp/docker-compose.yml) · [Compose oficial de Worker](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/hosting/docker/worker/docker-compose.yml)

Referencias en ejecución registradas para recuperación:

| Imagen de origen | Repo digest observado |
| --- | --- |
| Webapp `v4.5.4` | `sha256:5a14a51a353241639d084e0317c3b23956344b5b2d1c6dff0e77cc18e8f2370b` |
| Supervisor `v4.5.4` | `sha256:a3c28fc3bfca3bd2b5f08312395aceb75f1a8139db445dbceb9960f080c8c9d6` |

El build local del broker tiene ID `sha256:36139433d0bc9382cf7385a80f58f049fa72311a04715e1f77ed5b323c3813f4` y carece de RepoDigest. Conserva la imagen actual. El código dentro del contenedor coincide con el commit registrado. El contexto de build que quedó en el host contiene código distinto.

Aplica el delta de las recetas al Compose efectivo de **los mismos recursos**. Antes de editar, guarda la revisión y configuración anterior en el sistema de operación, con secretos restringidos a Coolify o al almacén aprobado. Comprueba dominios, labels de Traefik, secretos, puertos, volúmenes, redes y fuente Git o Raw Compose. El Supervisor en ejecución procede de `8084a0c050956de189df89962d801d2e1a66556f`, rama `CU-869e76cnn_Flujo-de-Agente-n8n-a-Triggerdev`, con `worker/docker-compose.yml`. Contrasta el candidato con ese Compose desplegado. Conserva las variables adicionales observadas en Webapp, incluidas `DATABASE_CONNECTION_LIMIT`, `DATABASE_CONNECTION_TIMEOUT`, `DATABASE_POOL_TIMEOUT`, `DEPLOY_IMAGE_PLATFORM`, `OBJECT_STORE_SERVICE`, `STREAM_ORIGIN` y `CLICKHOUSE_DB`. Mantén los digests efectivos de dependencias al preparar el despliegue si Coolify vuelve a hacer pull de tags móviles como `redis:7` o `latest`. Conserva las imágenes de tareas anteriores y registra qué despliegue está promovido en cada proyecto.

### Variables y dependencias

- **Webapp**. Conserva `EVENT_REPOSITORY_DEFAULT_STORE=clickhouse_v2`, `RUN_REPLICATION_ENABLED=1`, Redis y Electric, y la conexión directa de Prisma al PostgreSQL actual. Conserva el `ENCRYPTION_KEY` existente, que debe tener 32 bytes UTF-8, y verifica que Webapp y Supervisor comparten el mismo secreto gestionado. Las validaciones de arranque de 4.8.3 rechazan secretos de ejemplo inseguros. Mantén la base única de TriggerEU y comprueba que la configuración efectiva carece de DSN adicionales de Run Ops. [Variables de Webapp en 4.8.3](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/apps/webapp/app/env.server.ts)
- **Trazas y Logs**. El candidato empieza con `EVENT_REPOSITORY_V1_REROUTE_ENABLED=0` para conservar lecturas del almacén legacy, y `LOGS_SEARCH_DUAL_WRITE_ACTIVE=on` para indexar los eventos nuevos en Search v2. En esta topología lector, writer y eventos comparten el ClickHouse local. Comprueba overrides de repositorio por organización y DSN de lectura/escritura si existen en Coolify. [Variables de Webapp](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/apps/webapp/app/env.server.ts)
- **ClickHouse y S2**. El motor observado es `26.2.19.43` y el volumen activo es `sk040488wkgwcgo84w8k4gks_clickhouse-data-v26-2`, con marcador `.trigger-clickhouse-26.2-fresh`. `fresh` reusa ese volumen ya inicializado. Conserva sus datos, el modo y la ruta de montaje. El listado local carecía del volumen Bitnami. S2 conserva Streams v2, su basin y volumen, con API privada `10.21.30.15:4566/v1`. MinIO conserva `10.21.30.15:9002` y las credenciales planas `OBJECT_STORE_*` que generan las URL para los runners.
- **Worker y broker**. Conserva API y OTLP en `https://trigger.sidicom.es` y `/otel`, y `DOCKER_RUNNER_NETWORKS=supervisor` en `.16`. La URL del broker es `https://trigger-warm-broker.sidicom.es`. La receta resuelve un dispatch vacío a esa misma URL. Comprueba el valor efectivo de la verificación de entrega antes del corte. Su activación es optativa y el ejemplo usa `false`. Mantén el backend Redis, el prefijo configurado, `WARM_START_ALLOW_PLACEMENT_TAGS=true` y el resto de límites del broker. [Dispatch del Supervisor](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/apps/supervisor/src/index.ts) · [Cliente del runner](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/packages/core/src/v3/workers/warmStartClient.ts)
- **Aplicaciones**. Fija CLI, SDK y `@trigger.dev/build` donde se use a `4.8.3` con los lockfiles de cada proyecto. `TRIGGER_CLI_TAG` fija los ejemplos de comandos en el panel. La CLI efectiva se fija en el job o script de despliegue. Ensaya la invocación real del agente y la de CI con sus credenciales. Prueba login de CLI nuevo, incluida la aprobación por código si el navegador está en otra máquina. Revisa Zod (mínimo `3.25.56`), Bun legacy, IDs de Sessions con `/channels` o sufijo `:channels` y clientes de Query que usen tokens públicos o de run. Si la aplicación lee el canal `.in` de Sessions, confirma que lo hace desde backend con una clave secreta y que el token público conserva la lectura de `.out`. [Release 4.6.0](https://trigger.dev/changelog/v4-6-0#breaking-changes) · [Release 4.8.2](https://github.com/triggerdotdev/trigger.dev/releases/tag/v4.8.2) · [Release 4.8.3](https://github.com/triggerdotdev/trigger.dev/releases/tag/v4.8.3)
- **Agente de despliegue**. El recurso efectivo ejecuta la rama `stage` en `ecaba943f1a2ac583f256490ebae7e45c36a2f6e`. Actualiza la variable `TRIGGER_CLI_VERSION` en ese recurso y recrea el agente manteniendo detenida la entrada ordinaria de jobs. Comprueba la versión en el canario. El checkout local de `trigger-deploy-agent` en `main` no contiene el commit efectivo. El checkout local de `trigger-orange` tiene SDK/build/CLI `4.5.4` y su script también consume `TRIGGER_CLI_VERSION`. Contrasta cada revisión desplegada antes de preparar el lockfile y el build.

## Verificaciones de datos antes de la ventana

El entrypoint de Webapp aplica Prisma, Drizzle y Goose al arrancar. La comparación de los tags oficiales identifica 61 migraciones nuevas de Prisma en la base principal, 7 de Drizzle y ClickHouse `036`–`056`. El journal efectivo de cada motor determina qué queda por aplicar. El salto incluye DDL concurrente, cambios destructivos de Webhooks y de ClickHouse. Completa la preservación y prueba la restauración antes de arrancar la candidata contra los datos productivos. [Entrypoint](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/docker/scripts/entrypoint.sh) · [Prisma](https://github.com/triggerdotdev/trigger.dev/tree/v4.8.3/internal-packages/database/prisma/migrations) · [Drizzle](https://github.com/triggerdotdev/trigger.dev/tree/v4.8.3/internal-packages/dashboard-agent-db/drizzle) · [Goose](https://github.com/triggerdotdev/trigger.dev/tree/v4.8.3/internal-packages/clickhouse/schema)

### PostgreSQL

La lectura del 11 de noviembre encontró 795 migraciones Prisma aplicadas y cero sin terminar. La última fue `20260710120000_drop_remaining_run_graph_seam_foreign_keys`. Drizzle registraba dos migraciones. Las tablas `public."WebhookEndpoint"` y `public."WebhookDelivery"` todavía no existían. La base ocupaba 52 GB. Repite la comprobación en la ventana.

- Consulta `_prisma_migrations` y, si existe, `drizzle.__dashboard_agent_migrations`. En la copia de ensayo, valida la ausencia de migraciones activas/fallidas (`finished_at IS NULL AND rolled_back_at IS NULL`) e índices inválidos en `pg_index`. Registra tiempos, bloqueos y espacio de los índices concurrentes con datos representativos.
- Comprueba la unicidad de los entornos raíz `STAGING` y `PREVIEW`. En `"RuntimeEnvironment"` filtra `"parentEnvironmentId" IS NULL` y agrupa por `"projectId", "type"`. Resuelve los grupos con `count(*) > 1` antes de crear el índice. La lectura previa devolvió cero. [Índice único](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/internal-packages/database/prisma/migrations/20260714140000_runtime_environment_unique_staging_preview_root/migration.sql)
- Comprueba la existencia de `"WebhookEndpoint"` y `"WebhookDelivery"` con `to_regclass` y, si existen, si contienen filas. Las migraciones de endpoints compartidos y retención eliminan filas y recrean la tabla de entregas. Si hay datos útiles, prepara y ensaya su preservación antes de aplicar el DDL. [Endpoints compartidos](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/internal-packages/database/prisma/migrations/20260928120000_webhook_shared_endpoints/migration.sql) · [Retención](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/internal-packages/database/prisma/migrations/20261008092849_webhook_delivery_retention_classes/migration.sql)
- Registra una muestra de runs antiguos por store, despliegues activos, proyectos y sesiones que deban seguir accesibles. Contrasta `"TaskRun"."taskEventStore"` cuando exista y los overrides configurados. Incluye roles y extensiones requeridos para restore y cómo restablecer o comprobar la replicación lógica de Electric y de runs. Registra el punto de recuperación del PostgreSQL externo al stack si cualquier servicio auxiliar usa esa misma instancia.

### ClickHouse

La lectura del 11 de noviembre detectó unas **3,72 millones de filas físicas en Search v1** y **8,64 millones en raw v2**, con Search v2 aún sin crear y raw v1 sin partes activas. `default.goose_db_version` estaba en `35`. La propuesta es conservar un respaldo íntegro de Search v1 y validar el acceso al histórico necesario en Search v2 antes de aplicar `056`. `system.parts_columns` mostró `attributes_text` en todas las partes activas de raw v2 junto a `attributes` JSON. La equivalencia del contenido se comprueba en el ensayo.

Empieza con el catálogo y metadatos de partes. Ejecuta las consultas con el cliente del contenedor y la autenticación que ya utiliza, sin imprimir credenciales.

```sql
SELECT name
FROM system.tables
WHERE database = 'trigger_dev'
  AND name LIKE 'task_events%'
ORDER BY name;

SELECT maxIf(version_id, is_applied = 1) AS latest_applied
FROM default.goose_db_version;

SELECT table, sum(rows) AS part_rows, formatReadableSize(sum(bytes_on_disk)) AS bytes
FROM system.parts
WHERE active AND database = 'trigger_dev'
  AND table IN ('task_events_v1', 'task_events_v2', 'task_events_search_v1', 'task_events_search_v2')
GROUP BY table ORDER BY table;

SELECT table, name, type, default_kind
FROM system.columns
WHERE database = 'trigger_dev' AND table IN ('task_events_v1', 'task_events_v2')
  AND name IN ('attributes', 'attributes_text')
ORDER BY table, name;
```

Los conteos de partes sirven para dimensionar. Para decidir qué conservar, contrasta datos por día y muestras de runs en una copia, incluida su cobertura real de logs y atributos.

| Cambio | Comprobación y decisión |
| --- | --- |
| `045` y `046` retiran el puente y el JSON original de atributos | Guarda DDL y snapshot restaurable. En el clon, compara atributos en `attributes_text` antes y después para partes antiguas y recientes. Incluye trazas con errores, Unicode, objetos anidados y spans GenAI. Si hay diferencias, valida una materialización o exportación recuperable antes del corte. Drena escritores 4.5.4 antes del DDL final. [Migración 046](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/internal-packages/clickhouse/schema/046_drop_task_events_attributes.sql) |
| `055` cambia la materialización del índice de texto y `056` elimina `task_events_search_v1` y su vista | Si hay filas Search v1, conserva tabla, vista y datos, incluidos logs cuyo evento raw ya expiró. Valida búsquedas históricas y retención en el clon. Si el histórico debe seguir consultable en la UI, ensaya un backfill a Search v2 desde raw y Search v1 antes de promover el cambio. Aplica el DDL por etapas hasta `055` cuando el backfill requiera conservar los objetos de v1 en el destino. Incluso con Search v1 vacío, comprueba qué histórico raw debe aparecer en Search v2. El writer nuevo solo indexa eventos nuevos. [Migración 055](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/internal-packages/clickhouse/schema/055_disable_task_events_search_text_index.sql) · [Migración 056](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/internal-packages/clickhouse/schema/056_drop_task_events_search_v1.sql) |
| `task_events_v1` contiene eventos del store `clickhouse` | La tabla raw v1 sobrevive a `056`. Si hay histórico que conservar, valida lecturas con el reroute temporal en `0` y prepara la copia por días hacia `task_events_v2` según la guía oficial. Verifica los runs de muestra antes de activar `1`. Si el inventario demuestra que no hay datos legacy que leer, se puede usar `1` desde el corte. [Copia oficial de eventos legacy](https://trigger.dev/docs/self-hosting/docker#move-from-the-legacy-clickhouse-store) |

#### Ensayo de preservación de atributos y búsqueda

1. Restaura ClickHouse en el laboratorio. Captura `SHOW CREATE`, una copia íntegra restaurable de Search v1 y su vista y una muestra saneada de atributos raw con IDs de referencia. Registra ventanas, filas, bytes y huellas del histórico a preservar. Incluye logs que solo existan en Search v1.
2. Con escritores detenidos, aplica Goose hasta `044`. Comprueba `attributes_text` por partes y contrasta los valores con el JSON original. Si faltan valores persistidos, ensaya su materialización y espera a que terminen las mutaciones en `system.mutations`. Si necesitas fijar los conteos del clon, pausa las fusiones TTL y deja activas las fusiones ordinarias. `042` espera a que se retiren los índices de las partes existentes. Verifica valores y espacio antes de `045`/`046`. El DDL requiere que ningún escritor anterior vuelva a conectarse a ese esquema.
3. Aplica hasta `055`, conservando Search v1. Genera Search v2 a partir de raw v2 y de los registros Search v1 requeridos mediante el mapper `taskEventsSearch.ts` de `4.8.3`. Procesa rangos cerrados por fecha, detecta conflictos por identidad y contenido antes de deduplicar y verifica que una segunda pasada no inserta filas adicionales. Contrasta búsquedas de texto y atributos, orden, paginación y retención. El ensayo HA documenta una extracción del mapper y la comparación campo a campo. Para un backfill que use `LEFT ANTI JOIN` multiclave en 26.2, valida el resultado con `enable_join_runtime_filters=0` en esa consulta, por el fallo reproducido en el laboratorio de referencia. [Mapper upstream](https://github.com/triggerdotdev/trigger.dev/blob/v4.8.3/internal-packages/clickhouse/src/taskEventsSearch.ts) · [Evidencia 4.8.3 de HA](../../../coolify-trigger-ha/docs/updates/2026-11-trigger-v4.8.3-schema-inventory.md) · [Ensayo de backfill de referencia](../../../coolify-trigger-ha/docs/updates/2026-10-trigger-v4.8.1-logs-backfill-evidence.md)
4. Aplica `056` cuando el respaldo de Search v1 se haya restaurado en ensayo y el histórico requerido sea consultable en Search v2. Si se acuerda conservar parte del histórico en archivo, registra el alcance, plazo y procedimiento de consulta. Repite las comprobaciones después del DROP. La receta arranca con migración automática hasta `056`, por lo que en producción el procedimiento de preservación se completa antes de arrancarla.

En el clon, con ClickHouse ya sano, se puede usar la candidata como proceso Goose de una sola ejecución. El `CLICKHOUSE_URL` de esta receta incluye `secure=false`. Este bloque aplica la primera etapa. Después de verificar los atributos ejecuta `goose_lab up-to 55`. Tras validar la preservación de Search v1 y la consulta del histórico ejecuta `goose_lab up-to 56`. Usa `goose_lab status` para comprobar cada avance.

```sh
# Define compose_lab con el proyecto, Compose y env del clon aislado.
goose_lab() {
  compose_lab run --rm --no-deps -T --entrypoint /bin/sh webapp -ec '
    export GOOSE_DRIVER=clickhouse GOOSE_DBSTRING="$CLICKHOUSE_URL"
    export GOOSE_MIGRATION_DIR=/triggerdotdev/internal-packages/clickhouse/schema
    exec /usr/local/bin/goose "$@"
  ' sh "$@"
}

goose_lab status
goose_lab up-to 44
goose_lab status
```

### Punto de recuperación

Antes del primer DDL, fija una frontera común de escrituras y guarda un backup recuperable de PostgreSQL y del ClickHouse activo. Incluye Redis (colas y estado asociado), S2 (Streams v2), MinIO (objetos y snapshots), configuración de S2, bootstrap de Webapp y cualquier estado de auxiliares necesario para un restore coordinado. Usa backups consistentes por motor o snapshots tras detener escritores. Para restaurar ClickHouse por volumen, conserva el marcador, el esquema, los datos y `default.goose_db_version` en la misma captura. Restaura a un volumen distinto durante el ensayo. Registra hora UTC, IDs de backups, RPO aceptado, tiempo de restore medido y responsable. Las copias individuales de PostgreSQL y ClickHouse ya se restauraron en el SSD. Para la captura común y la capacidad actual de los hosts, usa la [guía del corte con Coolify y SSH](ventana-4.8.3.md#punto-de-recuperación-con-los-accesos-actuales).

## Ensayo aislado

1. Valida los dos Compose con Docker Compose y los valores de ejemplo. Para el runtime, usa valores sintéticos, nombres de proyecto y red exclusivos y volúmenes propios. Para un smoke en un solo Docker host, usa el override de abajo. Para ensayar la ruta split, usa una dirección privada del laboratorio alcanzable desde ambos hosts y el runner.
2. Arranca `v4.5.4` con datos sintéticos para el smoke y restaura una copia representativa en otro ensayo cuando sea necesario medir DDL o certificar histórico. Registra el estado inicial de ambos journals, la forma de las tablas y un run de referencia con logs, errores y sesión. Aísla schedules, webhooks y credenciales para impedir efectos hacia sistemas reales.
3. Detén escritores, captura y restaura el punto de recuperación. Ejecuta el salto con la misma imagen de Webapp y orden de arranque previstos. Mide migraciones, validez de índices, tablas, repeticiones y verificación del histórico. Prueba la vuelta a `4.5.4` sobre **los datos restaurados**, y cronometra el restore.
4. Arranca Supervisor `4.8.3`. Ejecuta la matriz de canarios y guarda señales de cada run, con un broker de prueba que cubra el backend Redis observado en TriggerEU. El repositorio local `coolify-trigger-ha` en `a3d18f6` aporta casos de warm start con un broker en memoria y un ensayo de migraciones desde 4.4.4. Ajusta origen, backend, S2 y topología al entorno de TriggerEU. [Matriz HA 4.8.3](../../../coolify-trigger-ha/docs/updates/2026-11-trigger-v4.8.3-validation-matrix.md) · [Contrato y prueba del broker](../../../coolify-trigger-ha/docs/warm-start-broker.md)

```sh
docker compose --env-file webapp/.env.example -f webapp/docker-compose.yml config --quiet
docker compose --env-file worker/.env.example -f worker/docker-compose.yml config --quiet
```

Para el smoke en Docker Desktop, usa proyectos distintos para Webapp y Worker y la misma red de laboratorio en `TRIGGER_RUNNER_NETWORK` y `DOCKER_RUNNER_NETWORKS`. Configura `SERVICE_URL_WEBAPP=http://webapp:3000` y arranca primero Webapp. Pasa el token de bootstrap sintético al Worker y usa `http://webapp:3000` como `TRIGGER_API_URL` y `http://webapp:3000/otel` como endpoint OTLP. Añade este override de Webapp al Compose de laboratorio para sondear los servicios desde los contenedores, con DNS de Docker y sin puertos publicados.

```yaml
services:
  webapp:
    environment:
      REALTIME_STREAMS_S2_ENDPOINT: http://s2:80/v1
      OBJECT_STORE_BASE_URL: http://minio:9000
    networks:
      default:
      runner:
        aliases: [webapp]
  minio:
    ports: !reset []
  s2:
    ports: !reset []
networks:
  default:
    internal: true
  runner:
    internal: true
```

Para reproducir el salto, guarda los Compose anteriores desde la revisión `84fee4f`, arranca con ellos y detén Supervisor y Webapp. Usa los mismos nombres de proyecto, red y volúmenes sintéticos para `goose_lab` y el arranque candidato. Mantén ClickHouse en marcha para la ejecución de Goose. Al terminar, retira primero el proyecto Worker y después el proyecto Webapp de laboratorio. La prueba del registry y del build de tareas requiere acceso a un registry aislado.

### Resultados del 11 de noviembre de 2026

| Ensayo | Resultado | Pendiente para TriggerEU |
| --- | --- | --- |
| Compose 5.6.1 | Ambas recetas validaron con `config --quiet`. El render confirmó los digests, el volumen de ClickHouse, los puertos privados y el dispatch vacío, heredado y explícito del broker. | Comparar el Compose generado por Coolify con el delta candidato. |
| Salto local en Docker Desktop ARM64 | Webapp y Supervisor pasaron de `4.5.4` a `4.8.3`. Prisma pasó de 795 a 856 sin migraciones pendientes ni índices inválidos. Drizzle terminó. Goose avanzó `35 → 44 → 55 → 56`. Search v1 y su vista seguían presentes en `55` y desaparecieron en `56`. Search v2 quedó disponible. Se conservaron las filas de prueba de PostgreSQL y ClickHouse y se registró el Supervisor nuevo. | Restauración representativa, validación del contenido histórico y tiempos de la ventana en AMD64. |
| Sondas locales | Webapp, MinIO y listado de basins S2 devolvieron `200`. Sessions anónima devolvió `401` con respuesta JSON. | Prueba funcional de `chat.agent`, OTLP, proxy TLS y endpoints privados desde un runner del worker remoto. |
| Broker `0.1.0` | Diez pruebas del servicio aprobadas. Con el código de `4873fe0`, Redis real y mensajes sintéticos se comprobaron conexión, miss, hit único y reenvío de `templateKey`, sin errores de entrega. | Canario con un runner real, Redis y la ruta HTTPS de TriggerEU. |
| Restauración parcial de PostgreSQL | Del backup de producción se restauraron el esquema y los dos journals en un PostgreSQL 16 local sin red. Se comprobaron 795 registros Prisma aplicados, 2 de Drizzle, 0 pendientes y 0 índices inválidos. | La restauración completa se hizo después en el SSD. [Resultado con copias de producción](#ensayo-con-copias-de-producción) |

### Ensayo con copias de producción

Se usaron el backup programado de PostgreSQL de las 03:00 UTC y el backup nativo de ClickHouse `trigger-rehearsal-20261111T090907Z-uB5pv05P`, capturado entre las 09:09 y las 09:12 UTC. Las copias corresponden a horas distintas. El ensayo mide la restauración y las migraciones de cada motor. La recuperación conjunta de producción requiere una frontera común de escrituras. Los archivos se guardaron en una imagen cifrada del SSD y los contenedores del ensayo se ejecutaron sin red ni puertos publicados.

- **PostgreSQL**. El archivo verificado por SHA-256 se restauró con `pg_restore --jobs=3` en PostgreSQL 16.15 ARM64 sobre ext4, dentro de una VM con disco en el SSD cifrado. El ensayo usó WAL mínimo para la carga masiva y mantuvo `fsync=on`. La restauración completa de esquema, datos, índices y restricciones tardó **1 h 43 min 27 s**, excluidas la transferencia y las pruebas de almacenamiento. El clon ocupa 54.145.596.439 bytes y el estado restaurado registró 795 migraciones Prisma aplicadas, 2 de Drizzle, cero pendientes y cero índices inválidos. El coste dominante fue el histórico PostgreSQL de `TaskEvent` y sus índices. Roles, ACL y configuración de replicación se deben comprobar en un ensayo de recuperación coordinada. [Carga masiva en PostgreSQL 16](https://www.postgresql.org/docs/16/populate.html)
- **Migración PostgreSQL**. Se volvió a `wal_level=logical` sobre el mismo volumen y se ejecutaron Prisma y Drizzle desde la imagen oficial 4.8.3, conectada solo al loopback del clon. Ambas terminaron en 7 segundos en este ensayo. Prisma pasó de 795 a 856 y Drizzle de 2 a 9, con cero pendientes y cero índices inválidos. Se mantuvieron los conteos de 932.077 runs, 3.431 despliegues, 7 proyectos, 54 entornos y 210 runs de sesión. En `TaskEvent` permanecieron iguales el fichero y tamaño del heap y los contadores de escritura, con 23.485.004 inserciones de la restauración. Una segunda ejecución dejó intactos ambos journals.
- **ClickHouse**. El ZIP verificado por SHA-256 se expandió en un volumen temporal de Docker y se restauró desde ese directorio en 55 segundos. Incluía `trigger_dev` y `default.goose_db_version`. La lectura inicial encontró 3.716.153 filas físicas en Search v1, 8.645.183 en raw v2 y cero diferencias entre `attributes_text` y el JSON de raw v2. Goose pasó de `35` a `44` y luego a `55`. Los conteos y huellas por día de los atributos raw y Search v1 coincidieron antes y después del DDL. El tiempo del ensayo incluye una espera en `042` hasta reanudar las mutaciones ordinarias.
- **Preparación del histórico**. El mapper oficial de 4.8.3 identificó 4.544.398 eventos elegibles de raw v2 en 112 días de inserción. Las 3.716.153 filas de Search v1 tenían correspondencia en el conjunto normalizado y no hubo claves con contenido contradictorio. El mapper ajustó la hora de finalización de 1.898 filas de Search v1 conforme a su límite de cinco minutos después de la inserción. El ZIP conserva sus valores originales.
- **Resultado de `056`**. Se insertaron 4.544.398 filas en Search v2 en 278 segundos, incluida la comparación por día. La segunda lectura detectó cero pendientes y cero conflictos. Tras eliminar la tabla y vista Search v1 en el clon, las huellas de Search v2, las búsquedas por palabra y subcadena y la muestra ordenada de 200 resultados coincidieron con las de antes de `056`. El ensayo mantuvo el TTL pausado. Aproximadamente 857.000 eventos, entre ellos unos 28.500 de Search v1, ya superaban los 90 días de Search v2 y quedan sujetos a retención cuando se reanuden las fusiones. El ZIP preserva el histórico original.

## Ventana de actualización

La [guía del corte con Coolify y SSH](ventana-4.8.3.md) reúne el preflight efectivo, los comandos de captura, el orden de drenaje y los tiempos que se registran en la ventana.

1. **Preparar**. En `teamnet-trigger-eu / production`, compara ambos Compose efectivos con los candidatos. Registra revisión, imágenes, estado, volumen y marker, baseline de cola, latencia, disco y errores. Confirma qué proyectos pueden producir tráfico por API, schedules, webhooks, reintentos o el deploy-agent y el mecanismo real para retener/reconciliar cada entrada. Comprueba que el registry sirve la imagen de cada canario y conserva los artefactos anteriores. Completa el ensayo de datos y decide con el responsable qué histórico debe seguir visible y cuándo se revierte.
2. **Drenar y capturar**. Pausa productores, schedules y despliegues de los entornos afectados con sus mecanismos de operación. Deja terminar los runs activos o acuerda cómo reanudar sus waits/checkpoints. Registra IDs y backlog pendiente, incluidos los recibidos durante la pausa. Detén Supervisor desde Coolify cuando no tome más trabajo y aísla la API del tráfico ordinario. Detén la Webapp anterior y los escritores que intervienen en la captura. Obtén el punto de recuperación consistente antes de aplicar migraciones.
3. **ClickHouse y Webapp**. Con escritores detenidos, deja ClickHouse sano en el volumen activo. Ejecuta el procedimiento por etapas con un contenedor de una sola ejecución de la imagen candidata, en la red del proyecto efectivo y con su `CLICKHOUSE_URL`. Usa únicamente el entrypoint de Goose durante esa fase. Después aplica el Compose al recurso de Webapp existente. Verifica el volumen y los endpoints/secretos antes de iniciar. Sigue los logs del entrypoint hasta completar Prisma y Drizzle y confirmar Goose en `56`. Comprueba journals, índices, queries históricas, espacio y salud de PostgreSQL, Redis, Electric, ClickHouse, S2 y MinIO. Comprueba `/healthcheck`, login y sondas Sessions/Realtime. Si falla una migración, conserva logs y journals para decidir entre corrección y restore antes de reintentar.
4. **Supervisor después**. Despliega el worker candidato desde su recurso. Verifica el registro en el dashboard y `/health` local, Docker `/_ping`, registry, rutas privadas y broker desde el contexto del worker. Mantén en pausa los productores externos. Si hay backlog elegible, comprueba antes de arrancar el worker cómo evitar que compita con el canario o se ejecute sin supervisión del operador.
5. **Canarios y tareas**. Lanza un run controlado de una versión ya desplegada para verificar la transición. Recrea el agente con `TRIGGER_CLI_VERSION=4.8.3` y comprueba su conexión a RabbitMQ. Con CLI/SDK/build `4.8.3` crea y ejecuta el despliegue canario de `staging` mediante la ruta real de build/push. Prueba la matriz. Después promueve por proyecto y valida un canario acordado en `production`. El agente/RabbitMQ debe procesar el trabajo y el worker debe descargar la imagen por su referencia exacta.
6. **Reapertura**. Reanuda productores, schedules, webhooks y despliegues en el orden acordado. Reconcílialos con la cola y con los IDs o claves de idempotencia guardados. Compara errores, backlog, tasa de éxito, latencia, uso de disco y nuevas trazas con la referencia previa. Registra el estado final en el inventario una vez verificada la versión efectiva. [Runbook de sondas](diagnostico.md) · [Observabilidad](observabilidad.md)

## Matriz de aceptación

| Ruta | Resultado esperado |
| --- | --- |
| API, login y Realtime | `/healthcheck` 200. Sessions y Realtime devuelven 401 JSON en las sondas anónimas. Login de CLI `4.8.3`, credencial de CI existente y API autenticada funcionan. |
| Deploy y cold start | Job de despliegue finaliza, push al registry, Supervisor descarga y crea un `runner-*` en su red local. Un run anterior y un run construido con 4.8.3 completan con la salida esperada. |
| Warm hit | Ejecuta dos runs secuenciales del mismo deployment y preset, separados lo suficiente para observar al primer runner idle. El segundo reutiliza la identidad del runner. Correlaciona IDs de run, del runner y el incremento de hits de `/healthz`. |
| Warm miss y fallback | En el laboratorio prueba un deployment incompatible y un broker no disponible o un runner warm interrumpido con el verifier activado. El cold start completa y cada nonce produce un solo efecto. En producción, valida cold y warm con el broker activo y la política efectiva. |
| S2 y MinIO | Desde el runner, S2 responde al prefijo privado y MinIO devuelve 200 en su sonda. Dos turnos de `chat.agent` conservan contexto y snapshot al cambiar de runner. Prueba recarga a mitad de turno y renovación de token si el flujo de la aplicación las usa. |
| OTLP y ClickHouse | Traza con spans y errores legibles en un run nuevo, eventos en `task_events_v2`, el log canario aparece en Search v2 y los spans GenAI alimentan `llm_metrics` cuando corresponda. Contrasta muestras históricas de los stores presentes. Investiga descartes o retrasos de dual-write con los logs de Webapp y diferencias raw/Search v2. |
| Operación | Webapp y Supervisor sanos, sin acumulación de cola ni incremento sostenido de errores frente al baseline de la ventana. Registra alcance de lo ensayado, digests en ambos hosts, hora UTC, IDs de canarios y evidencia de restauración. |

El release posterior documenta correcciones para la ruta Logs del panel, el offload de payload de tareas hijas y la repetición de arranques durante esperas largas por capacidad. Incluye esos casos en el canario si corresponden al tráfico de TriggerEU. Si se reproduce un fallo que impide la aceptación, conserva la evidencia antes de decidir el siguiente paso. [Release 4.8.4](https://github.com/triggerdotdev/trigger.dev/releases/tag/v4.8.4)

## Recuperación

- **Antes de cambios en los datos**. Detén la candidata, restituye revisión, digests y variables anteriores en los mismos recursos y confirma que los journals y datos siguen en la frontera previa. Arranca primero Webapp, luego Supervisor y verifica API, colas y un canario.
- **Si la falla está limitada a warm starts**. En el recurso del worker vacía `TRIGGER_WARM_START_URL` y `TRIGGER_WARM_START_DISPATCH_URL` y recrea Supervisor. Comprueba un cold run y que la cola baja. Conserva las variables anteriores para volver a activar el broker tras el diagnóstico.
- **Después de aplicar migraciones o aceptar escrituras nuevas**. Pausa entradas, detén writers y conserva una copia del estado fallido y de los trabajos posteriores al corte. Decide entre corregir hacia delante o restaurar. Para volver a 4.5.4 restaura PostgreSQL y ClickHouse de la misma frontera y el estado asociado que haga falta para coherencia de colas, snapshots y sesiones. Apunta las recetas previas a los datos restaurados. La reversión de `056` recrea objetos vacíos, y cambiar solo el tag deja los esquemas modificados. Arranca Webapp y Supervisor previos, verifica histórico y canarios y reconcilia los runs y entregas posteriores al punto de recuperación antes de reabrir tráfico. Restituye `TRIGGER_CLI_VERSION=4.4.4` en el agente si se cambió y recupera los despliegues de tareas anteriores según el inventario.
