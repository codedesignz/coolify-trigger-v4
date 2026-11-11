# Diagnóstico de TriggerEU Prod

Ante un incidente, registra la hora UTC, el síntoma, el entorno de Trigger.dev y, si existe, el ID del run, la tarea y la versión desplegada. El filtro `TriggerEU / Prod` de Grafana identifica la infraestructura. Los runners de `staging` y `production` comparten el worker.

| Síntoma | Dónde empezar |
| --- | --- |
| La UI o la API devuelve un error de DNS, TLS, `502` o `503` | Traefik y Webapp en `10.21.30.15`. Compara el endpoint público con la sonda interna. |
| Se acumulan runs en cola o el worker aparece desconectado | Runs y concurrencia en el entorno afectado. Después revisa Supervisor, proxy Docker y daemon en `10.21.30.16`. |
| El run falla al arrancar o al descargar su imagen | Logs de Supervisor y estado del runner en `10.21.30.16`. Comprueba la etiqueta desplegada y el registry. |
| El run ejecuta pero fallan sesiones, streaming o snapshots | API de sesiones y Realtime. Verifica S2 y MinIO desde el worker y desde el contexto de red afectado. |
| La UI está disponible pero faltan trazas o métricas de IA | Logs de Webapp, envío OTLP desde Supervisor y almacenamiento de eventos en ClickHouse. |
| Faltan logs o métricas en Grafana | Comprueba las fuentes y la cobertura de [observabilidad](observabilidad.md). Contrasta con Docker en el host correspondiente. |

## UI y API

Ejecuta estas sondas desde un punto con acceso a la URL pública. El formato conserva el código HTTP y el tipo de contenido sin imprimir cuerpos de respuesta.

```sh
base=https://trigger.sidicom.es
curl -sS --max-time 10 -o /dev/null -w '%{http_code} %{content_type}\n' "$base/"
curl -sS --max-time 10 -o /dev/null -w '%{http_code} %{content_type}\n' "$base/healthcheck"
curl -sS --max-time 10 -o /dev/null -w '%{http_code} %{content_type}\n' \
  -H 'Content-Type: application/json' --data '{}' "$base/api/v1/sessions"
curl -sS --max-time 10 -o /dev/null -w '%{http_code} %{content_type}\n' \
  "$base/realtime/v1/sessions/test/out"
```

El 11 de noviembre de 2026, la raíz redirigía con `302` y `/healthcheck` devolvía `200`. Sin credenciales, Sessions devolvía `401 application/problem+json` y Realtime devolvía `401 application/json`. Una respuesta HTML inesperada en las rutas API orienta a revisar la regla de enrutamiento o la versión de Webapp.

En `10.21.30.15`, identifica la Webapp actual y comprueba su healthcheck interno. Si responde `200` y falla el acceso público, revisa DNS, certificado y Traefik `coolify-proxy` para el dominio. Si falla la sonda interna, mira Webapp y sus dependencias en el mismo host.

```sh
docker ps -a --filter label=com.docker.compose.project=sk040488wkgwcgo84w8k4gks \
  --format '{{.Names}} {{.Image}} {{.Status}}'
webapp=$(docker ps -q \
  --filter label=com.docker.compose.project=sk040488wkgwcgo84w8k4gks \
  --filter label=com.docker.compose.service=webapp)
docker exec "$webapp" node -e 'fetch("http://127.0.0.1:3000/healthcheck", {signal: AbortSignal.timeout(5000)}).then(r => console.log(r.status))'
```

## Runs pendientes o fallos al arrancar

1. En el panel de Trigger.dev, abre Runs en el entorno afectado. Si afecta a una tarea o versión concreta, revisa su despliegue, el estado del run, la cola y sus límites de concurrencia. Si afecta a varias colas, revisa si el entorno está pausado y comprueba el estado del worker.
2. En `10.21.30.16`, comprueba que Supervisor y `docker-proxy` estén sanos. Consulta los logs locales de Supervisor alrededor del inicio del run. Busca mensajes de conexión con Webapp, dequeuing, creación de contenedor o descarga de imagen. Un healthcheck local verde confirma la respuesta de la API de Supervisor. Confirma la conexión del worker también en el panel de Trigger.dev.
3. Si Supervisor intenta iniciar el run, localiza el `runner-…` con la hora y la imagen que figuran en sus logs. Comprueba estado, código de salida, OOM y red. Los runners recientes pueden desaparecer por el borrado automático. Correlaciona los contenedores en `Exited` con la hora del fallo.
4. Para errores de descarga, compara la referencia de la imagen del despliegue con el mensaje de error. En runners activos se observó `10.21.30.14:5000`; la configuración de Supervisor tenía `DOCKER_REGISTRY_URL=registry.sidicom.es`. Revisa la ruta y las credenciales del registry correspondiente a la imagen. Si el fallo ocurre durante el despliegue de tareas, revisa también el recurso `trigger-deploy-agent`, RabbitMQ y sus logs en `10.21.30.15`.

```sh
# En 10.21.30.16
docker ps -a --filter label=com.docker.compose.project=z0wos4o0kg8osw40wc4kkkcg \
  --format '{{.Names}} {{.Image}} {{.Status}}'
supervisor=$(docker ps -q \
  --filter label=com.docker.compose.project=z0wos4o0kg8osw40wc4kkkcg \
  --filter label=com.docker.compose.service=supervisor)
docker logs --since 30m --tail 200 "$supervisor"
docker exec "$supervisor" node -e 'Promise.all(process.argv.slice(1).map(async url => { const r = await fetch(url, {signal: AbortSignal.timeout(5000)}); console.log(r.status, url); await r.body?.cancel(); }))' \
  http://localhost:8020/health http://docker-proxy:2375/_ping \
  https://trigger.sidicom.es/healthcheck http://10.21.30.14:5000/v2/
docker ps --filter name=runner- --format '{{.Names}} {{.Image}} {{.Status}}'
```

Desde Supervisor se observó `200` en su API local, en Docker `/_ping` y en el healthcheck público de Webapp. El registry privado devolvió `401` en `/v2/` sin credenciales, lo que confirma el acceso HTTP. Para un runner concreto, sustituye el argumento por su nombre actual.

```sh
docker inspect --format 'status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} networks={{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' '<runner>'
docker logs --since 30m --tail 200 '<runner>'
```

Si los errores afectan a la capacidad de ejecutar contenedores, revisa el journal de Docker con `journalctl -u docker --since '-30 min' -n 150 --no-pager`, el espacio e inodos con `df -h` y `df -i`, y la presión de CPU y memoria en cAdvisor y node-exporter. Si el problema apunta a warm starts, comprueba `https://trigger-warm-broker.sidicom.es/healthz` y los logs del recurso `trigger-warm-broker` en `10.21.30.15`. La sonda interna equivalente es `http://127.0.0.1:18080/healthz` en ese host.

Para investigar un warm start concreto, consulta desde Supervisor `/healthz` y comprueba conexión a Redis, runners idle y el delta de hits, misses y errores de entrega durante el intervalo. Correlaciona deployment, preset y el ID del runner de ambos runs. Si la API del broker está sana y no hay hits, verifica su política de placement tags y el registro del runner idle. En 4.8.3 revisa también `TRIGGER_WARM_START_DISPATCH_URL`. El [plan de actualización](actualizacion-4.8.3.md#recuperación) indica cómo operar temporalmente en cold start.

## Dependencias de Webapp

| Componente | Señal y comprobación inicial |
| --- | --- |
| PostgreSQL | Si Webapp falla al iniciar, migrar o leer datos, revisa el estado del contenedor y sus logs. El healthcheck usa `pg_isready`. |
| Redis | Para errores de conexión o dequeuing, correlaciona Webapp y Supervisor con los logs de Redis y comprueba `redis-cli ping` dentro de Redis. |
| ElectricSQL | Si falla la sincronización de datos, revisa PostgreSQL y el healthcheck `/v1/health` de Electric en su puerto interno `3000`. |
| ClickHouse | Para errores de ingestión, timeline o métricas de IA, revisa el estado de salud en Docker, los logs de ClickHouse y Webapp y `EVENT_REPOSITORY_DEFAULT_STORE=clickhouse_v2`. Tras 4.8.3, si existe la traza del run pero falta en Logs, contrasta `task_events_v2` con `task_events_search_v2`, el dual-write y el intervalo histórico copiado. Consulta la [preservación de atributos y búsqueda](actualizacion-4.8.3.md#ensayo-de-preservación-de-atributos-y-búsqueda). |
| S2 | Si fallan Sessions o streams, revisa logs de Webapp y S2, configuración del endpoint y conectividad privada desde ambos hosts. |
| MinIO | Si falla un snapshot de `chat.agent`, comprueba salud HTTP, URL privada anunciada y los errores de autorización de la petición real. |

En `10.21.30.15`, sustituye `clickhouse` por el servicio afectado. Localiza el contenedor en la primera salida y usa su nombre en el comando de logs.

```sh
docker ps -a --filter label=com.docker.compose.project=sk040488wkgwcgo84w8k4gks \
  --filter label=com.docker.compose.service=clickhouse --format '{{.Names}} {{.Status}}'
docker logs --since 30m --tail 200 'clickhouse-sk040488wkgwcgo84w8k4gks'
```

Sondas privadas observadas desde ambos hosts y desde Supervisor.

```sh
curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' http://10.21.30.15:4566/v1
curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' http://10.21.30.15:9002/minio/health/live
```

El `404` de S2 en el prefijo `/v1` comprueba conectividad HTTP. Para verificar una sesión, usa el estado y los errores de una petición real de esa sesión. MinIO devuelve `200` si responde su sonda de salud. Si las sondas funcionan desde el host y falla un runner, comprueba su red Docker `supervisor` y repite la sonda desde su contexto si sigue activo y dispone de cliente HTTP.

## Correlación y evidencia

- Para Webapp y Traefik en `10.21.30.15`, empieza por Loki con la ventana del incidente. Para Supervisor, runners, proxy Docker y bases de datos, empieza por `docker logs --since 30m --tail 200 <contenedor>` en el host del servicio. Usa cAdvisor para métricas de contenedores y node-exporter para recursos del host. [Consultas y cobertura de Grafana](observabilidad.md)
- Si el run ejecuta y faltan trazas, revisa los errores de envío a `https://trigger.sidicom.es/otel` en Supervisor y los de ingestión en Webapp y ClickHouse. Usa el ID del run y la hora para correlacionar las señales.
- Al compartir hallazgos, incluye componente, hora UTC, versión y señales relevantes. Redacta credenciales, cookies, enlaces firmados y payloads. En Docker, consulta campos concretos de estado con `--format`. El entorno y los comandos de healthcheck pueden contener secretos.
- Si el diagnóstico apunta a una intervención, deja identificado el recurso de Coolify y el impacto esperado sobre runs activos, colas y datos persistentes. Consulta el [inventario](inventario.md) para comprobar el recurso y sus dependencias.

[Índice de documentación](README.md)
