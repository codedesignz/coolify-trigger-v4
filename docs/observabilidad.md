# Observabilidad de TriggerEU Prod

Verificado el 11 de noviembre de 2026 con consultas a Grafana y el inventario de los servidores.

## Qué abrir en Grafana

Los paneles están en la carpeta **Coolify**.

| Señal | Panel | Filtros de la monoinstancia |
| --- | --- | --- |
| Logs de aplicación y proxy | [Coolify Logs Explorer](https://grafana.sidicom.es/d/ceexp8uiaujgga/coolify-logs-explorer?var-project=TriggerEU&var-environment=Prod) | **Project** `TriggerEU`, **Environment** `Prod`, **App** `Trigger` o `Traefik`. **Container** filtra por nombre y **Search** filtra el texto. |
| CPU, memoria y red de contenedores | [Coolify Resources Monitor](https://grafana.sidicom.es/d/htoVWdxGt/coolify-resources-monitor) | **Server** con el destino cAdvisor del nodo. Acota con **Container Name** o **Resource**. |
| CPU, memoria, disco, red y uptime del host | [Coolify Servers Monitor](https://grafana.sidicom.es/d/xfpJB9FGx/coolify-servers-monitor) | **Server** con el destino Node Exporter del nodo. |
| Vista rápida de presión en los hosts | [Coolify · Host Overview](https://grafana.sidicom.es/d/coolify-hosts-summary/coolify-c2b7-host-overview) | **Hosts** `exporter-trigger` y `exporter-trigger-worker1`. |
| Métricas HTTP y backends del proxy | [Traefik Monitor](https://grafana.sidicom.es/d/n5bu_kv4k/traefik-monitor) | **Node** `10.21.30.15:8080`. Para el proxy de `.16`, revisa los logs locales y sus métricas de contenedor. |

En **Explore** usa `loki` (UID `fee81myilboxsc`) para LogQL y `prometheus-coolify` (UID `feetl7josn75se`) para PromQL. Empieza con los últimos 30 minutos y ajusta el intervalo al incidente.

## Loki y cobertura de logs

El selector base de producción es `{project="TriggerEU",environment="Prod"}`. Los streams consultados tenían las etiquetas `project`, `environment`, `app` y `service_name`. Tanto `app` como `service_name` mostraron los valores `Trigger` y `Traefik`. El campo `container_name` se extrae del JSON del evento.

En `10.21.30.15`, el driver Docker `fluentd` de `webapp` y Traefik entrega sus logs al contenedor `coolify-log-drain` (Fluent Bit, `127.0.0.1:24224`). La consulta de la última hora encontró `webapp-…` con `app="Trigger"` y `/coolify-proxy` con `app="Traefik"`. RabbitMQ y el agente de despliegue también usan el driver `fluentd`. La búsqueda por sus nombres de contenedor bajo `TriggerEU` / `Prod` quedó sin resultados en las últimas 24 horas. Para esos dos servicios, empieza por los logs locales.

En `10.21.30.15`, PostgreSQL, Redis, Electric, S2, ClickHouse, MinIO y el warm-start broker usan `json-file`. En `10.21.30.16`, Supervisor, Docker Proxy, los runners y Traefik también usan `json-file`. El worker carece de un `coolify-log-drain` local y el filtro por Supervisor, Docker Proxy o runner quedó sin resultados en las últimas 24 horas. Consulta estos logs en el host correspondiente o en el recurso de Coolify si los muestra.

Volumen de logs por aplicación en los últimos 30 minutos. En Explore usa el modo **Instant** para obtener un total por aplicación.

```logql
sum by (app) (
  count_over_time({project="TriggerEU",environment="Prod"}[30m])
)
```

Patrones de error por aplicación en los últimos 15 minutos. El filtro busca texto. Abre los eventos alrededor del pico para confirmar su origen.

```logql
sum by (app) (
  count_over_time(
    {project="TriggerEU",environment="Prod"}
    |~ "(?i)error|exception|fatal|panic|timeout"
    [15m]
  )
)
```

Eventos de la webapp mediante el nombre del contenedor. El patrón admite el prefijo `/` que aparece en el JSON recibido por Loki.

```logql
{project="TriggerEU",environment="Prod",app="Trigger"}
| json container_name="container_name"
| __error__=""
| container_name=~"/?webapp-.*"
```

Para buscar una ejecución concreta, acota al intervalo y añade un filtro de línea con el ID de run. Si faltan logs, comprueba primero que el selector base devuelve datos. En el nodo del servicio, identifica el nombre actual del contenedor y revisa su driver y salida reciente.

```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}'
contenedor='<nombre del contenedor>'
docker inspect --format '{{.HostConfig.LogConfig.Type}}' "$contenedor"
docker logs --since 30m --tail 200 "$contenedor"
```

Si falta en Loki un servicio de `.15` que usa `fluentd`, comprueba el estado y los logs de `coolify-log-drain` y compara el intervalo con los eventos locales del servicio.

## Prometheus, cAdvisor y Node Exporter

| Servidor | `job="cadvisor"` | `job="node_exporter"` |
| --- | --- | --- |
| `10.21.30.15` (`Tn-Trigger`) | `cadvisor-trigger.sidicom.es` | `exporter-trigger.sidicom.es` |
| `10.21.30.16` (`Tn-Trigger-Worker1`) | `cadvisor-trigger-worker1.sidicom.es` | `exporter-trigger-worker1.sidicom.es` |

El valor de `instance` en las consultas es el nombre DNS de la tabla. cAdvisor escucha en el puerto interno `8080` de su contenedor y se publica por el proxy. Node Exporter usa la red del host y escucha en `9100`.

Comprueba primero los cuatro destinos. `up = 1` indica que Prometheus pudo recoger métricas. `up = 0` indica un fallo de scrape. Si falta una serie, revisa el datasource, el intervalo y la presencia del destino en Prometheus. Cruza la señal con el estado del nodo en Coolify.

```promql
up{job=~"cadvisor|node_exporter",instance=~"(cadvisor|exporter)-trigger(-worker1)?[.]sidicom[.]es"}
```

### cAdvisor para contenedores

Las métricas de los servicios Compose de Trigger llevan `container_label_coolify_projectName="teamnet-trigger-eu"` y `container_label_coolify_environmentName="production"`. Los valores `TriggerEU` y `Prod` corresponden a Loki. El propio cAdvisor y Node Exporter se despliegan bajo el proyecto `services` en Coolify. Para ver todos los contenedores de un nodo usa `instance` y `name`.

CPU en núcleos por servicio Compose. Para memoria, usa el mismo selector con `container_memory_working_set_bytes` y conserva la agrupación por instancia y servicio.

```promql
sum by (instance, container_label_com_docker_compose_service) (
  rate(container_cpu_usage_seconds_total{
    job="cadvisor",
    instance=~"cadvisor-trigger(-worker1)?[.]sidicom[.]es",
    container_label_coolify_projectName="teamnet-trigger-eu",
    container_label_coolify_environmentName="production"
  }[5m])
)
```

Para runners efímeros del worker usa el nombre que asigna el Supervisor. La consulta siguiente devuelve memoria de trabajo en bytes por runner mientras hay muestras.

```promql
max by (instance, name) (
  container_memory_working_set_bytes{
    job="cadvisor",
    instance="cadvisor-trigger-worker1.sidicom.es",
    name=~"runner-.*"
  }
)
```

### Node Exporter para el host

Usa el `job="node_exporter"` y las instancias `exporter-…`. Revisa CPU y carga, memoria disponible, espacio e inodos del sistema de archivos y tráfico de red. Para investigar capacidad de disco, valida en el nodo el punto de montaje que contiene los datos o volúmenes del servicio.

Porcentaje de memoria utilizada respecto a la memoria total de cada host.

```promql
100 * (
  1 -
  node_memory_MemAvailable_bytes{job="node_exporter",instance=~"exporter-trigger(-worker1)?[.]sidicom[.]es"} /
  node_memory_MemTotal_bytes{job="node_exporter",instance=~"exporter-trigger(-worker1)?[.]sidicom[.]es"}
)
```

Porcentaje de espacio utilizado respecto a la capacidad del sistema de archivos raíz.

```promql
100 * (
  1 -
  node_filesystem_avail_bytes{job="node_exporter",instance=~"exporter-trigger(-worker1)?[.]sidicom[.]es",mountpoint="/"} /
  node_filesystem_size_bytes{job="node_exporter",instance=~"exporter-trigger(-worker1)?[.]sidicom[.]es",mountpoint="/"}
)
```

## Correlación durante un incidente

| Síntoma | Primera comprobación | Correlación |
| --- | --- | --- |
| HTTP 5xx o latencia de la API | Loki con `app="Traefik"` y `app="Trigger"` en la misma ventana. | Métricas de Traefik y de `webapp` en `.15`. Estado de las dependencias locales. |
| Run en cola o con error de ejecución | Logs de `webapp` para el ID de run y logs del Supervisor en `.16`. | cAdvisor para `supervisor` y `runner-…`, Node Exporter del worker y logs locales del runner si sigue disponible. |
| Contenedor lento o reiniciado | cAdvisor para el servicio afectado. | Node Exporter del mismo host y estado, reinicios o eventos en Docker y Coolify. |
| Desaparecen métricas o logs | Comprueba `up` por destino o el selector Loki base. | Comprueba los contenedores cAdvisor, Node Exporter o el log drain del nodo y los logs locales del servicio. |

Registra el intervalo UTC, el nodo, el servicio, el ID de run si existe y la consulta que devolvió la evidencia.
