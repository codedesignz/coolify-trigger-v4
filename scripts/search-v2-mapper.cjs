// Stream rows through the exact writer shipped in the pinned 4.8.3 image.
const fs = require("node:fs");
const { once } = require("node:events");
const { createInterface } = require("node:readline");
const { registerHooks } = require("node:module");
const { pathToFileURL, fileURLToPath } = require("node:url");

const base = "/triggerdotdev/internal-packages/clickhouse/src/";
const source = process.argv[2];
if (source !== "raw" && source !== "v1") throw new Error("Unknown source");

registerHooks({
  resolve(specifier, context, next) {
    try {
      return next(specifier, context);
    } catch (error) {
      if (error.code !== "ERR_MODULE_NOT_FOUND" || !specifier.endsWith(".js") || !context.parentURL) throw error;
      const resolved = new URL(specifier.slice(0, -3) + ".ts", context.parentURL);
      const path = fileURLToPath(resolved);
      if (!path.startsWith(base) || !fs.existsSync(path)) throw error;
      return { url: resolved.href, shortCircuit: true };
    }
  },
});

const stats = { input: 0, mapped: 0, excluded: 0, changedTriggeredTime: 0 };
function requireField(condition) {
  if (!condition) throw new Error("Invalid source field");
}
function asNanoseconds(value) {
  const [seconds, fraction] = value.split(".");
  return BigInt(seconds) * 1_000_000_000n + BigInt(fraction);
}

(async () => {
  const { toTaskEventSearchV2RowIfEligible } = await import(pathToFileURL(base + "taskEventsSearch.ts"));
  const stream = createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of stream) {
    stats.input++;
    const { attributes_text, original_triggered_ns, valid_utf8, ...event } = JSON.parse(line);
    requireField(valid_utf8 === 1 || valid_utf8 === true);
    requireField(typeof attributes_text === "string");
    requireField(/^\d+$/.test(event.start_time) && /^\d+$/.test(event.duration));
    requireField(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$/.test(event.inserted_at));
    let attributes;
    let parsed = false;
    // Use upstream eligibility before parsing attributes it never reads.
    const mapped = toTaskEventSearchV2RowIfEligible({
      ...event,
      get attributes() {
        if (!parsed) {
          attributes = JSON.parse(attributes_text);
          parsed = true;
        }
        return attributes;
      },
    }, new Date(0));
    if (mapped === undefined) {
      stats.excluded++;
      continue;
    }
    stats.mapped++;
    if (source === "v1" && BigInt(original_triggered_ns) !== asNanoseconds(mapped.triggered_timestamp)) {
      stats.changedTriggeredTime++;
    }
    if (!process.stdout.write(JSON.stringify({ ...mapped, source }) + "\n")) {
      await once(process.stdout, "drain");
    }
  }
  console.error(JSON.stringify(stats));
})().catch(() => {
  // Content of log rows and parsing exceptions stays inside the pipe.
  console.error(JSON.stringify({ failure: "mapper", ...stats }));
  process.exitCode = 1;
});
