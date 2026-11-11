#!/usr/bin/env python3
"""Prepara, copia y verifica el histórico de Logs en Search v2 para Trigger.dev 4.8.3."""

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile

PROD_IP = "10.21.30.15"
PROD_HOST = "tn-trigger"
PROD_PROJECT = "sk040488wkgwcgo84w8k4gks"
PROD_VOLUME = PROD_PROJECT + "_clickhouse-data-v26-2"
DATA_PATH = "/var/lib/clickhouse"
DATA_MARKER = DATA_PATH + "/.trigger-clickhouse-26.2-fresh"
LAB_LABEL = "com.teamnet.trigger.search-v2-lab"
CH_VERSION = "26.2.19.43"
WEB = "ghcr.io/triggerdotdev/trigger.dev:v4.8.3@sha256:54aa67fa90cd1fc88ce11ae670e6dbb8f12d2ba8b39e839e882d9e32bb8bdb1f"
SOURCE = {"raw": "task_events_v2", "v1": "task_events_search_v1"}
TARGET = "task_events_search_v2"
VIEW_V1 = "task_events_search_mv_v1"
TABLE_SQL = "trigger_dev." + TARGET
# Resuelve las credenciales dentro del contenedor. El cliente recibe un fichero
# privado en tmpfs, sin pasar la contraseña como argumento ni escribirla a disco.
CLIENT_SHELL = r"""
user="${CLICKHOUSE_USER:-default}"
if [ -z "${CLICKHOUSE_PASSWORD:-}" ]; then
  exec clickhouse-client --host 127.0.0.1 --port 9000 --user "$user" "$@"
fi
umask 077
config="$(mktemp /dev/shm/trigger-search-v2.XXXXXXXX)"
trap 'rm -f "$config"' EXIT
{
  printf '%s' '<clickhouse><password>'
  printf '%s' "$CLICKHOUSE_PASSWORD" | sed 's/\&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'
  printf '%s\n' '</password></clickhouse>'
} > "$config"
clickhouse-client --config-file "$config" --host 127.0.0.1 --port 9000 --user "$user" "$@"
"""
FIELDS = ["environment_id", "organization_id", "project_id", "triggered_timestamp",
          "trace_id", "span_id", "run_id", "task_identifier", "start_time", "inserted_at",
          "message", "error_message", "search_text", "kind", "status", "duration", "parent_span_id"]
KEY = ["organization_id", "environment_id", "triggered_timestamp", "trace_id", "span_id",
       "projection_fingerprint"]
FIELD_SQL = ",".join(FIELDS)
KEY_SQL = ",".join(KEY)
TUPLE = "tuple(" + FIELD_SQL + ")"
# Con inserted_at al final se distinguen las colisiones de timestamp de las de contenido.
COMPARE_FIELDS = [field for field in FIELDS if field != "inserted_at"] + ["inserted_at"]
COMPARE_TUPLE = "tuple(" + ",".join(COMPARE_FIELDS) + ")"
SAME_NON_TIME_FIELDS = " AND ".join(
    f"tupleElement(min_payload,{i})=tupleElement(max_payload,{i})"
    for i in range(1, len(FIELDS))
)
SETTINGS = ("max_memory_usage=1800000000,max_bytes_before_external_group_by=402653184,"
            "max_bytes_before_external_sort=402653184,max_execution_time=900")

HELP = r"""
Requisitos de la ventana
  Verifica un respaldo restaurable de trigger_dev y default.goose_db_version.
  Mantén los escritores detenidos y conserva los volúmenes activos.
  Durante Goose 44 y 55 deja las fusiones ordinarias disponibles para la 042.
  Si necesitas fijar los conteos, pausa únicamente TTL en esa fase.

  Después de Goose 55, ejecuta SYSTEM STOP TTL MERGES y SYSTEM STOP MERGES
  en cada tabla de trigger_dev: task_events_v2, task_events_search_v1,
  task_events_search_v2.
  Espera a que terminen las fusiones y mutaciones activas. Conserva esta
  condición entre comandos, incluido el segundo verify tras Goose 56.
  --confirm-merges-frozen confirma que el operador ha realizado este paso.

Orden
  stage   Crea la base de staging indicada y transforma las dos fuentes.
  apply   Inserta claves ausentes en Search v2. Repite apply para comprobar
          que inserta cero filas. Conserva el primer apply en
          search-483-apply-first.json y la repetición en search-483-apply-repeat.json.
  verify  Comprueba cobertura y huellas sin escribir en ClickHouse.
          Ejecútalo antes y después de aplicar Goose 56 por separado.
          Registra cada resultado en search-483-verify-55.json o search-483-verify-56.json.
  Usa la misma base y carpeta de evidencia en todos estos comandos.

  El script nunca ejecuta Goose ni cambia el estado de fusiones o TTL.
  Después de la última verificación, reanuda SYSTEM START MERGES en
  task_events_v2 y task_events_search_v2. Reanuda SYSTEM START TTL MERGES
  según la decisión de retención. Conserva el respaldo histórico y los
  informes del corte. Verifica antes de que Coolify recree ClickHouse.
  Usa una carpeta de evidencia privada por corte. Si stage quedó incompleto,
  conserva sus resultados y usa otra base y carpeta para repetirlo.

Ejemplos
  %(prog)s stage --profile lab --context desktop-linux --container ch-lab \
    --lab-id test-483 --stage-db trigger_eu_search_stage_test_483 \
    --evidence-dir /ruta/privada/ch-lab --confirm-merges-frozen
  %(prog)s stage --profile trigger-eu --container ID_CLICKHOUSE \
    --stage-db trigger_eu_search_stage_corte_483 \
    --evidence-dir /ruta/privada/corte-483 --confirm-merges-frozen

  El contenedor de laboratorio requiere la etiqueta
    com.teamnet.trigger.search-v2-lab=<lab-id>
  y red none, sin puertos publicados. En TriggerEU ejecuta el script desde
  el host 10.21.30.15, con ClickHouse sano y el contenedor Webapp detenido.
  Descarga antes la imagen Webapp 4.8.3 fijada en el script. El mapper se
  ejecuta en esa imagen con red none y el script no descarga imágenes.
"""


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args, *, timeout=30):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=DOCKER_ENV)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Se agotó el tiempo de una comprobación local") from None
    if result.returncode:
        code = re.search(r"\(([A-Z][A-Z_]{2,})\)", result.stderr)
        reason = f" ({code.group(1)})" if code else ""
        raise RuntimeError(f"Falló un comando local con código {result.returncode}{reason}")
    return result.stdout.strip()


def short_hostname(name):
    return name.split(".", 1)[0].casefold()


DOCKER_ENV = {key: value for key, value in os.environ.items() if key not in {
    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"
}}


def docker_command(profile, context):
    if profile == "trigger-eu":
        need(sys.platform.startswith("linux"), "El perfil trigger-eu requiere el host Linux de TriggerEU")
        addresses = json.loads(command(["ip", "-j", "address", "show"]))
        need(any(address["local"] == PROD_IP for interface in addresses
                 for address in interface.get("addr_info", []) if address.get("family") == "inet"),
             "La interfaz local de TriggerEU no tiene la IP esperada")
        endpoint = "unix:///var/run/docker.sock"
        socket_paths = [Path("/var/run/docker.sock")]
    else:
        if context is None:
            context = command(["docker", "context", "show"])
        need(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", context),
             "Nombre de contexto Docker inválido")
        endpoint = command(["docker", "context", "inspect", "--format",
                            "{{.Endpoints.docker.Host}}", context])
        socket_paths = [Path("/var/run/docker.sock"), Path("/run/docker.sock"),
                        Path.home() / ".docker/run/docker.sock",
                        Path(f"/run/user/{os.geteuid()}/docker.sock")]
    need(endpoint.startswith("unix:///"), "Solo se permite un socket Docker Unix local")
    path = Path(endpoint.removeprefix("unix://")).resolve()
    need(path in {candidate.resolve() for candidate in socket_paths} and path.is_socket(),
         "El contexto no usa un socket local reconocido")
    docker = ["docker", "--host", f"unix://{path}"]
    system = command(docker + ["info", "--format", "{{.OSType}}|{{.OperatingSystem}}|{{.Name}}"])
    os_type, operating_system, hostname = system.split("|", 2)
    need(os_type == "linux", "El daemon Docker debe ejecutar contenedores Linux")
    if profile == "trigger-eu":
        need(short_hostname(hostname) == PROD_HOST and
             short_hostname(socket.gethostname()) == PROD_HOST, "El daemon no es Tn-Trigger")
    else:
        need(PROD_HOST not in (short_hostname(hostname), short_hostname(socket.gethostname())),
             "El host de TriggerEU requiere el perfil trigger-eu")
        if operating_system == "Docker Desktop":
            need(sys.platform in ("darwin", "linux") and short_hostname(hostname) == "docker-desktop",
                 "Identidad inesperada de Docker Desktop")
        else:
            need(sys.platform.startswith("linux") and short_hostname(hostname) == short_hostname(socket.gethostname()),
                 "El daemon del laboratorio no pertenece al host local")
    return docker


def private_directory(path):
    need(path.is_absolute() and not path.is_symlink(), "La carpeta de evidencia debe ser absoluta y sin enlace")
    directory = path.resolve()
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.stat()
    need(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid() and not metadata.st_mode & 0o077,
         "La carpeta de evidencia debe pertenecer al operador y ser privada (0700)")
    return directory


@contextmanager
def lock_target(container_id):
    # La exclusión se mantiene aunque otra invocación elija otra carpeta o staging.
    lock_path = Path("/tmp") / f"trigger-search-v2-{container_id}.lock"
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "w") as lock:
        metadata = os.fstat(lock.fileno())
        need(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid() and
             not metadata.st_mode & 0o077, "El fichero de exclusión local no es privado")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Ya hay otro backfill activo para este contenedor") from None
        yield


class Backfill:
    def __init__(self, args):
        self.args = args
        self.docker = docker_command(args.profile, args.context)
        target = self.inspect(args.container)
        self.container_id = target["id"]
        need(re.fullmatch(r"[0-9a-f]{64}", self.container_id), "ID de contenedor inválido")
        self.stage = args.stage_db + ".candidates"
        self.client = self.docker + ["exec", "-i", self.container_id, "/bin/sh", "-ec", CLIENT_SHELL, "sh",
                                     "--log_queries=0", "--session_timezone=UTC", "--max_threads=2"]
        self.check_target(target)
        self.evidence = private_directory(args.evidence_dir)

    def inspect(self, container):
        template = ('{"id":{{json .Id}},"labels":{{json .Config.Labels}},'
                    '"state":{{json .State.Status}},"paused":{{json .State.Paused}},'
                    '"health":{{with index .State "Health"}}{{json .Status}}{{else}}null{{end}},'
                    '"network":{{json .HostConfig.NetworkMode}},'
                    '"ports":{{json .HostConfig.PortBindings}},"mounts":{{json .Mounts}}}')
        return json.loads(command(self.docker + ["inspect", "--type", "container", "--format", template, container]))

    def check_target(self, target):
        labels = target["labels"] or {}
        need(target["state"] == "running" and not target["paused"], "ClickHouse no está en ejecución")
        mounts = [mount for mount in target["mounts"] or [] if mount["Destination"] == DATA_PATH]
        if self.args.profile == "lab":
            need(labels.get(LAB_LABEL) == self.args.lab_id and target["network"] == "none" and not target["ports"],
                 "Contenedor de laboratorio sin etiqueta esperada o con red/puertos")
            need(labels.get("com.docker.compose.project") != PROD_PROJECT and
                 not any(mount.get("Name") == PROD_VOLUME for mount in mounts),
                 "El perfil lab no admite el proyecto o volumen de TriggerEU")
        else:
            need(labels.get("com.docker.compose.project") == PROD_PROJECT and
                 labels.get("com.docker.compose.service") == "clickhouse",
                 "El contenedor no es el servicio ClickHouse de TriggerEU")
            need(target["health"] == "healthy", "ClickHouse no está sano")
            need(len(mounts) == 1 and mounts[0]["Type"] == "volume" and
                 mounts[0]["Name"] == PROD_VOLUME and mounts[0]["RW"], "Volumen activo de ClickHouse inesperado")
            command(self.docker + ["exec", self.container_id, "test", "-f", DATA_MARKER])
            self.check_writers()

    def check_writers(self):
        if self.args.profile != "trigger-eu":
            return
        ids = command(self.docker + ["ps", "-aq", "--no-trunc",
                    "--filter", f"label=com.docker.compose.project={PROD_PROJECT}",
                    "--filter", "label=com.docker.compose.service=webapp"]).splitlines()
        need(ids and all(re.fullmatch(r"[0-9a-f]{64}", container) for container in ids),
             "No se ha encontrado el contenedor Webapp detenido del recurso")
        states = command(self.docker + ["inspect", "--type", "container",
                       "--format", "{{.State.Status}}", *ids]).splitlines()
        need(len(states) == len(ids) and all(state in ("exited", "created") for state in states),
             "Hay una Webapp activa o en transición en el mismo recurso")

    def sql(self, statement):
        return command(self.client + ["--query", statement], timeout=930)

    def rows(self, statement):
        return [json.loads(line) for line in self.sql(statement + " FORMAT JSONEachRow").splitlines()]

    def record(self, filename, value):
        path = self.evidence / filename
        fd, filename = tempfile.mkstemp(dir=self.evidence)
        temp = Path(filename)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    def journal(self, phase):
        need(self.sql("SELECT version()") == CH_VERSION, "Versión de ClickHouse inesperada")
        need(self.sql("SELECT timezone()") in ("UTC", "Etc/UTC"), "ClickHouse debe usar UTC en la sesión")
        journal = int(self.sql("SELECT maxIf(version_id, is_applied=1) FROM default.goose_db_version"))
        need(journal == 55 or (phase == "verify" and journal == 56),
             "Se requiere Goose 55. Solo verify admite también Goose 56")
        expected = {TARGET: "ReplacingMergeTree", SOURCE["raw"]: "MergeTree"}
        if journal == 55:
            expected.update({SOURCE["v1"]: "MergeTree", VIEW_V1: "MaterializedView"})
        tables = self.rows("SELECT name,engine,partition_key,sorting_key FROM system.tables "
                           "WHERE database='trigger_dev' AND name IN ('task_events_v2',"
                           "'task_events_search_v1','task_events_search_mv_v1','task_events_search_v2')")
        need({row["name"]: row["engine"] for row in tables} == expected, "Inventario Search inesperado")
        target = next(row for row in tables if row["name"] == TARGET)
        need(target["partition_key"] == "toDate(inserted_at)" and
             target["sorting_key"].replace(" ", "") == KEY_SQL, "Clave de Search v2 inesperada")
        return journal

    def check_quiescent(self):
        self.check_writers()
        names = "'task_events_v2','task_events_search_v1','task_events_search_v2'"
        active = self.sql(f"SELECT count() FROM system.merges WHERE database='trigger_dev' AND table IN ({names})")
        pending = self.sql(f"SELECT count() FROM system.mutations WHERE database='trigger_dev' AND table IN ({names}) AND NOT is_done")
        need(active == pending == "0", "Aún hay fusiones o mutaciones activas en las tablas del backfill")

    def create_stage(self):
        need(self.sql(f"SELECT count() FROM system.databases WHERE name='{self.args.stage_db}'") == "0",
             f"Ya existe {self.args.stage_db}. Conserva esa base y revisa el informe")
        schema = self.rows("SELECT name,type,default_kind,default_expression FROM system.columns "
                      f"WHERE database='trigger_dev' AND table='{TARGET}' ORDER BY position")
        need([item["name"] for item in schema] == FIELDS + ["projection_fingerprint"],
             "Columnas de Search v2 inesperadas")
        projection = schema[-1]
        need(projection["type"] == "UInt128" and projection["default_kind"] == "DEFAULT" and
             projection["default_expression"].startswith("reinterpretAsUInt128(sipHash128("),
             "Huella de proyección inesperada")
        definitions = ",".join(f"{field['name']} {field['type']}" for field in schema[:-1])
        self.sql(f"CREATE DATABASE {self.args.stage_db}")
        self.sql(f"CREATE TABLE {self.stage} ({definitions}, "
            f"projection_fingerprint UInt128 DEFAULT {projection['default_expression']}, "
            "source LowCardinality(String)) ENGINE=MergeTree PARTITION BY toDate(inserted_at) "
            f"ORDER BY ({KEY_SQL})")


    def stream_source(self, tag):
        table = "trigger_dev." + SOURCE[tag]
        total = int(self.sql(f"SELECT count() FROM {table}"))
        original = "toString(toUnixTimestamp64Nano(triggered_timestamp))" if tag == "v1" else "''"
        select = ("SELECT environment_id,organization_id,project_id,trace_id,span_id,run_id,task_identifier,"
                  "toString(toUnixTimestamp64Nano(start_time)) AS start_time,toString(inserted_at,'UTC') AS inserted_at,"
                  "message,kind,status,toString(duration) AS duration,parent_span_id,attributes_text,"
                  f"{original} AS original_triggered_ns,"
                  "toUInt8(isValidUTF8(message) AND isValidUTF8(attributes_text) AND "
                  "isValidUTF8(environment_id) AND isValidUTF8(organization_id) AND "
                  "isValidUTF8(project_id) AND isValidUTF8(run_id) AND isValidUTF8(trace_id) AND "
                  "isValidUTF8(span_id) AND isValidUTF8(parent_span_id) AND isValidUTF8(task_identifier)) AS valid_utf8 "
                  f"FROM {table} FORMAT JSONEachRow")
        # Store no intermediate JSONL files. Suppress raw-row server errors in the streaming stages.
        mapper = str(Path(__file__).resolve().with_name("search-v2-mapper.cjs"))
        node = self.docker + ["run", "--rm", "-i", "--pull", "never", "--network", "none", "--read-only",
                         "--memory", "768m", "--label", f"com.teamnet.trigger.search-v2-mapper={self.args.stage_db}",
                         "--mount", f"type=bind,src={mapper},dst=/fixture/mapper.cjs,readonly",
                         "--entrypoint", "node", WEB, "/fixture/mapper.cjs", tag]
        insert = (f"INSERT INTO {self.stage} ({FIELD_SQL},source) "
                  "SETTINGS input_format_json_throw_on_bad_escape_sequence=0,max_partitions_per_insert_block=0,"
                  "max_insert_block_size=65536,min_insert_block_size_rows=32768,"
                  "min_insert_block_size_bytes=16777216,max_memory_usage=1500000000 "
                  "FORMAT JSONEachRow")
        with subprocess.Popen(self.client + ["--query", select], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, env=DOCKER_ENV) as extract:
            with subprocess.Popen(node, stdin=extract.stdout, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=DOCKER_ENV) as transform:
                extract.stdout.close()
                with subprocess.Popen(self.client + ["--query", insert], stdin=transform.stdout,
                                      stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, env=DOCKER_ENV) as load:
                    transform.stdout.close()
                    diagnostics = transform.stderr.read().decode("utf-8", "replace")
                    codes = [load.wait(), transform.wait(), extract.wait()]
        stats = {}
        for line in diagnostics.splitlines():
            try:
                candidate = json.loads(line)
            except ValueError:
                continue
            if isinstance(candidate, dict):
                counts = ("input", "mapped", "excluded", "changedTriggeredTime")
                if all(type(candidate.get(key)) is int and candidate[key] >= 0 for key in counts):
                    stats = {key: candidate[key] for key in counts}
        need(codes == [0, 0, 0], f"Falló el flujo {tag} (carga, mapper, lectura): {codes}. Conteos: {stats}")
        need(stats.get("input") == total and stats["mapped"] + stats["excluded"] == total,
             f"Cambió el conteo de {tag} durante la lectura")
        staged = int(self.sql(f"SELECT count() FROM {self.stage} WHERE source='{tag}'"))
        need(staged == stats["mapped"], f"Conteo de staging inesperado para {tag}")
        print(f"{tag}: {stats}", flush=True)
        return stats


    def day_list(self):
        statement = ("SELECT DISTINCT toDate(inserted_at) FROM ("
                     f"SELECT inserted_at FROM {self.stage} UNION ALL SELECT inserted_at FROM {TABLE_SQL}) ORDER BY 1")
        days = self.sql(statement).splitlines()
        need(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) for day in days), "Fecha de partición inesperada")
        return days


    def both(self, day):
        predicate = f"toDate(inserted_at)=toDate('{day}')"
        return (f"SELECT {FIELD_SQL},projection_fingerprint,source FROM {self.stage} WHERE {predicate} "
                f"UNION ALL SELECT {FIELD_SQL},projection_fingerprint,'target' AS source "
                f"FROM {TABLE_SQL} WHERE {predicate}")


    def assess(self, day):
        # Compare physical rows before ReplacingMergeTree can hide a conflicting variant.
        # Min/max over the full typed tuple is exact and avoids storing all distinct payloads.
        statement = ("SELECT countIf(raw_rows+v1_rows>0) AS eligible_keys,"
                     " countIf(raw_rows>0 AND v1_rows>0) AS overlap_keys,"
                     " countIf(raw_rows>0 AND v1_rows=0) AS raw_only_keys,"
                     " countIf(raw_rows=0 AND v1_rows>0) AS v1_only_keys,"
                     " countIf(raw_rows+v1_rows>0 AND target_rows=0) AS missing_keys,"
                     " countIf(raw_rows+v1_rows=0 AND target_rows>0) AS target_only_keys,"
                     " countIf(min_payload!=max_payload) AS conflicting_keys,"
                     f" countIf(min_payload!=max_payload AND {SAME_NON_TIME_FIELDS}) AS inserted_at_only_conflicting_keys,"
                     " countIf(target_rows>0) AS target_keys,"
                     " sum(target_rows) AS physical_target_rows,"
                     " countIf(raw_rows+v1_rows>0 AND toDateTime(triggered_timestamp)+INTERVAL 90 DAY<=now())"
                     " AS past_v2_ttl_keys,"
                     " groupBitXorIf(cityHash64(min_payload), raw_rows+v1_rows>0) AS eligible_xor,"
                     " sumIf(cityHash64(min_payload), raw_rows+v1_rows>0) AS eligible_sum,"
                     " groupBitXorIf(cityHash64(min_payload), target_rows>0) AS target_xor,"
                     " sumIf(cityHash64(min_payload), target_rows>0) AS target_sum,"
                     " minIf(cityHash64(min_payload), raw_rows+v1_rows>0) AS candidate_sample_hash"
                     " FROM (SELECT triggered_timestamp,"
                     f" min({COMPARE_TUPLE}) AS min_payload, max({COMPARE_TUPLE}) AS max_payload,"
                     " countIf(source='raw') AS raw_rows,countIf(source='v1') AS v1_rows,"
                     " countIf(source='target') AS target_rows"
                     f" FROM ({self.both(day)}) GROUP BY {KEY_SQL}) SETTINGS {SETTINGS}")
        result, = self.rows(statement)
        return {key: int(value) for key, value in result.items()}


    def insertion(self, day):
        # The UNION/GROUP BY is the absence check, so no JOIN runtime filter participates.
        self.sql(f"INSERT INTO {TABLE_SQL} ({FIELD_SQL}) SELECT untuple(payload) FROM "
            f"(SELECT any({TUPLE}) AS payload FROM ({self.both(day)}) GROUP BY {KEY_SQL}"
            " HAVING countIf(source='target')=0) SETTINGS "
            f"{SETTINGS},exclude_materialize_skip_indexes_on_insert='idx_search_text',async_insert=0")


    def run(self, phase):
        journal = self.journal(phase)
        self.check_quiescent()
        identity = {"container": self.container_id, "profile": self.args.profile, "stage_db": self.args.stage_db}
        manifest_path = self.evidence / "search-483-stage.json"
        first_apply_path = self.evidence / "search-483-apply-first.json"
        if phase == "stage":
            need(not manifest_path.exists(), "La carpeta ya contiene un staging; reusa apply o elige otra carpeta")
            command(self.docker + ["image", "inspect", "--format", "{{.Id}}", WEB])
            self.create_stage()
            staged = {}
            for tag in SOURCE:
                self.check_quiescent()
                staged[tag] = self.stream_source(tag)
        else:
            need(manifest_path.is_file(), "Falta el manifiesto de un stage completado")
            manifest = json.loads(manifest_path.read_text())
            need(manifest["identity"] == identity, "El staging pertenece a otro contenedor, perfil o base")
            staged = manifest["sources"]
        for tag in SOURCE:
            count = int(self.sql(f"SELECT count() FROM {self.stage} WHERE source='{tag}'"))
            need(count == staged[tag]["mapped"], f"Cambió el conteo del staging {tag}")
            if journal == 55 or tag == "raw":
                total = int(self.sql(f"SELECT count() FROM trigger_dev.{SOURCE[tag]}"))
                need(total == staged[tag]["input"], f"Cambió el conteo de la fuente {tag}")
        days = self.day_list()
        need(days, "No hay particiones de origen elegibles")
        before = {day: self.assess(day) for day in days}
        phase_label = f"verify-{journal}" if phase == "verify" else phase
        self.record(f"search-483-{phase_label}-before.json", {"journal": journal, "days": before})
        conflicts = sum(value["conflicting_keys"] for value in before.values())
        eligible = sum(value["eligible_keys"] for value in before.values())
        missing = sum(value["missing_keys"] for value in before.values())
        v1_only = sum(value["v1_only_keys"] for value in before.values())
        timestamp_conflicts = sum(value["inserted_at_only_conflicting_keys"] for value in before.values())
        print(f"{phase}: days={len(days)} eligible={eligible} missing={missing} "
              f"v1_only={v1_only} conflicting={conflicts} inserted_at_only={timestamp_conflicts}", flush=True)
        need(conflicts == 0, "Hay variantes antes de deduplicar; revisa el informe agregado")
        self.check_quiescent()
        if phase == "stage":
            self.record(manifest_path.name, {"identity": identity, "sources": staged})
        elif phase == "apply" and not first_apply_path.exists():
            after = self.apply(before, journal)
            self.check_quiescent()
            self.record(first_apply_path.name, {"journal": journal, "inserted": missing,
                                               "before": before, "after": after})
            print(f"apply: inserted={missing}; todas las filas coinciden y quedan cero pendientes", flush=True)
        else:
            need(first_apply_path.is_file(), "Falta el informe de un apply completado")
            first = json.loads(first_apply_path.read_text())
            self.verify(before, missing, first["after"])
            self.check_quiescent()
            if phase == "apply":
                self.record("search-483-apply-repeat.json", {"journal": journal, "inserted": 0, "days": before})
                print("apply: inserted=0; cobertura y huellas sin cambios", flush=True)
            else:
                self.record(f"search-483-{phase_label}.json", {"journal": journal, "days": before})
                print("verify: cobertura completa y conteos y huellas del destino sin cambios", flush=True)

    def apply(self, before, journal):
        after = {}
        for day, stats in before.items():
            if stats["missing_keys"]:
                self.check_quiescent()
                self.insertion(day)
            result = self.assess(day)
            need(result["conflicting_keys"] == 0 and result["missing_keys"] == 0,
                 f"Faltan filas o no coinciden los valores para {day}")
            need(result["physical_target_rows"] == stats["physical_target_rows"] + stats["missing_keys"],
                 f"Conteo físico inesperado en el destino para {day}")
            fingerprint = ("eligible_keys", "eligible_xor", "eligible_sum")
            need(all(result[key] == stats[key] for key in fingerprint),
                 f"Cambió la huella de candidatos para {day}")
            after[day] = result
            self.record("search-483-apply-after.json", {"journal": journal, "days": after})
        return after

    def verify(self, before, missing, applied):
        need(missing == 0, "La cobertura del destino es incompleta")
        fingerprints = ("target_keys", "physical_target_rows", "target_xor", "target_sum", "candidate_sample_hash")
        need(set(applied) == set(before), "Cambió el conjunto de particiones del destino")
        need(all(before[day][key] == applied[day][key] for day in before for key in fingerprints),
             "Cambiaron los conteos o huellas del destino")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=HELP,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phase", choices=("stage", "apply", "verify"))
    parser.add_argument("--profile", choices=("lab", "trigger-eu"), required=True)
    parser.add_argument("--container", required=True, help="ID o nombre del contenedor ClickHouse")
    parser.add_argument("--context", help="Contexto Docker local (solo lab)")
    parser.add_argument("--lab-id", help="Valor de la etiqueta de laboratorio (solo lab)")
    parser.add_argument("--stage-db", required=True, help="Base exclusiva con prefijo trigger_eu_search_stage_")
    parser.add_argument("--evidence-dir", required=True, type=Path, help="Directorio absoluto y privado")
    parser.add_argument("--confirm-merges-frozen", required=True, action="store_true",
                        help="Confirma que las fusiones ordinarias y TTL están pausadas después de Goose 55")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", args.container):
        parser.error("--container inválido")
    if not re.fullmatch(r"trigger_eu_search_stage_[a-z0-9_]{1,40}", args.stage_db):
        parser.error("--stage-db debe usar el prefijo indicado y un sufijo de minúsculas, dígitos o _")
    if not args.evidence_dir.is_absolute():
        parser.error("--evidence-dir debe ser una ruta absoluta")
    if args.profile == "lab":
        if not args.lab_id or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", args.lab_id):
            parser.error("El perfil lab requiere un --lab-id válido")
    elif args.lab_id is not None or args.context is not None:
        parser.error("--lab-id y --context se usan solo con el perfil lab")
    return args


def main():
    os.umask(0o077)
    args = parse_args()
    try:
        backfill = Backfill(args)
        with lock_target(backfill.container_id):
            backfill.run(args.phase)
    except KeyboardInterrupt:
        print("Backfill interrumpido por el operador", file=sys.stderr)
        return 130
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        # Los mensajes de nuestros guards están acotados; el resto puede contener
        # paths o contenido del proceso externo y se reporta solo por tipo.
        message = str(error) if type(error) is RuntimeError else type(error).__name__
        print(f"Backfill detenido: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
