/**
 * Structured application logging.
 *
 * One JSON object per line so hosting-provider log drains can index fields.
 * Callers must never pass personal data (names, emails, addresses, tokens)
 * in `fields`; pass identifiers such as request IDs, handles and counts.
 */
type Level = "debug" | "info" | "warn" | "error";
type Fields = Record<string, string | number | boolean | null | undefined>;

const LEVELS: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };
const configured = (process.env.LOG_LEVEL as Level | undefined) ?? (process.env.NODE_ENV === "production" ? "info" : "debug");
const threshold = LEVELS[configured] ?? 20;

function emit(level: Level, msg: string, fields?: Fields) {
  if (LEVELS[level] < threshold) return;
  const line = JSON.stringify({ time: new Date().toISOString(), level, msg, ...fields });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

export const log = {
  debug: (msg: string, fields?: Fields) => emit("debug", msg, fields),
  info: (msg: string, fields?: Fields) => emit("info", msg, fields),
  warn: (msg: string, fields?: Fields) => emit("warn", msg, fields),
  error: (msg: string, fields?: Fields) => emit("error", msg, fields),
};

/** Reduce an unknown thrown value to loggable fields without leaking secrets. */
export function errorFields(err: unknown): Fields {
  if (err instanceof Error) {
    return { errorName: err.name, errorMessage: err.message.slice(0, 500) };
  }
  return { errorMessage: String(err).slice(0, 500) };
}
