# Operación IT de TriggerEU Prod

Estas instrucciones se aplican a todo el repositorio. Úsalas para orientar auditorías, incidentes, mantenimiento y actualizaciones de la monoinstancia de Trigger.dev gestionada por Coolify.

## Punto de partida

| Host | Qué aloja | Dónde identificarlo |
| --- | --- | --- |
| `10.21.30.15` · `Tn-Trigger` | Webapp detrás de Traefik, PostgreSQL, Redis, Electric, ClickHouse, S2 y MinIO. También el warm-start broker y el agente de despliegue con RabbitMQ. | Recurso principal `sk040488wkgwcgo84w8k4gks`. [Receta Webapp](webapp/docker-compose.yml) |
| `10.21.30.16` · `Tn-Trigger-Worker1` | Supervisor, proxy del socket de Docker y contenedores efímeros `runner-*`. | Aplicación `trigger-worker1`, recurso `z0wos4o0kg8osw40wc4kkkcg`. [Receta Worker](worker/docker-compose.yml) |

- Abre el [índice de operación](docs/README.md) para ver la topología. Usa el [inventario](docs/inventario.md) para localizar servicios, volúmenes, dominios y puertos, y el [runbook](docs/diagnostico.md) para elegir las sondas según el síntoma.
- En Coolify, localiza el proyecto `teamnet-trigger-eu` y el entorno `production`. Las recetas del repositorio describen el despliegue previsto. Contrasta el estado efectivo con Coolify y Docker, y localiza contenedores por las etiquetas `com.docker.compose.project` y `com.docker.compose.service`.
- La API pública está en `https://trigger.sidicom.es`. El supervisor usa el mismo dominio para la API y `/otel` para OTLP. El registry observado en las imágenes de los runners es `10.21.30.14:5000`. Comprueba la referencia exacta de la imagen si falla un pull.
- `supervisor` es una red Docker local a cada host. En el worker, los runners se conectan a ella con `DOCKER_RUNNER_NETWORKS=supervisor`. Los runners acceden a S2 y MinIO mediante los endpoints privados de `.15` en `:4566` y `:9002`.

## Auditoría y diagnóstico

1. Identifica el componente, el intervalo UTC y el entorno del run en Trigger.dev. El worker ejecuta tareas de `staging` y `production` en la misma infraestructura.
2. Para inventario y auditoría usa inspecciones de solo lectura en Coolify, Grafana y los dos hosts. El acceso autorizado por SSH como `root` permite comprobar imágenes y digests, estado, redes, puertos publicados, volúmenes y salud. Usa campos específicos de `docker inspect --format` y ventanas acotadas de logs. Los volcados de entorno, los comandos de healthcheck, los tokens y los payloads pueden contener secretos. Redáctalos al compartir evidencias.
3. En Grafana, usa Loki con `project="TriggerEU"` y `environment="Prod"` para Webapp y Traefik. Consulta los logs de Supervisor y runners en Docker en `.16`. Usa cAdvisor para contenedores y Node Exporter para recursos del host. Los servicios de Compose aparecen en cAdvisor con las etiquetas de Coolify `teamnet-trigger-eu` / `production`. [Paneles, selectores y cobertura](docs/observabilidad.md)
4. Si la auditoría incluye red, distingue entre un puerto publicado y el alcance efectivo desde otras redes. En particular, comprueba quién puede llegar a PostgreSQL en `.15:5432` y conserva S2 en la red privada. Si incluye recuperación, verifica en Coolify o en el sistema de backups qué se copia, cuándo y qué restauraciones se han probado. El inventario inicial dejó esa comprobación pendiente.
5. Registra el recurso, la versión observada, la evidencia y el impacto de cada hallazgo. Una auditoría puede concluir con una propuesta de intervención. Ejecuta cambios en producción cuando formen parte del encargo autorizado.

## Preparar y ejecutar una actualización

1. Registra las versiones y digests en ejecución, la versión objetivo y el Compose de cada recurso afectado. Revisa las notas oficiales y las migraciones de la versión objetivo. Coordina Webapp, Supervisor y, cuando corresponda, SDK, CLI y el build de las tareas en la misma línea de versión. [Receta y notas de actualización](README.md)
2. Identifica dependencias, runs activos y datos afectados. Si hay migraciones, verifica backups restaurables de los datos afectados y deja definido el rollback antes de desplegar. Un cambio de imagen puede requerir restaurar también el esquema y los datos. Para ClickHouse, verifica el volumen activo y su marcador. El inventario observó `clickhouse-data-v26-2` inicializado en modo `fresh`. Comprueba la existencia de cualquier volumen legado o backup antes de incluirlo en el plan.
3. Prepara los cambios de Compose y de variables de ejemplo en el repositorio. Valida la receta con Docker Compose usando valores de prueba y `config --quiet`. Revisa en Coolify las variables aplicables por nombre y conserva los valores sensibles en Coolify. Aplica los despliegues autorizados desde los recursos de Coolify. Sus Compose generados en los hosts sirven para contrastar el estado efectivo.
4. En una actualización conjunta, verifica primero el estado de Webapp y sus dependencias. Después comprueba que el Supervisor se registra, toma ejecuciones y puede descargar la imagen y crear un runner. Sigue las sondas del runbook para la API, S2 y MinIO. Si el cambio afecta a trazas, comprueba el envío OTLP y la aparición de eventos de runs nuevos en ClickHouse con `EVENT_REPOSITORY_DEFAULT_STORE=clickhouse_v2`. Para un cambio funcional, valida con un run de prueba en el entorno acordado.
5. Registra las versiones finales, las comprobaciones y cualquier punto pendiente. Actualiza el inventario, el runbook o los selectores de Grafana cuando cambie el despliegue efectivo.
