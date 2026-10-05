function stableValue(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `[${value.map((v) => stableValue(v)).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a.localeCompare(b),
    );
    const body = entries.map(([k, v]) => `${JSON.stringify(k)}:${stableValue(v)}`).join(",");
    return `{${body}}`;
  }
  return JSON.stringify(String(value));
}

function fnv1a64(input: string): string {
  let hash = BigInt("0xcbf29ce484222325");
  const prime = BigInt("0x100000001b3");
  const mod = BigInt("0xffffffffffffffff");
  for (let i = 0; i < input.length; i += 1) {
    hash ^= BigInt(input.charCodeAt(i));
    hash = (hash * prime) & mod;
  }
  return hash.toString(16).padStart(16, "0");
}

export function computeSceneHash(input: unknown): `sha256:${string}` {
  const canonical = stableValue(input);
  return `sha256:${fnv1a64(canonical)}`;
}
