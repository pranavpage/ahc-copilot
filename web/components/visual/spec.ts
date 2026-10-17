// A filled visual block from the show_visual tool artifact (copilot/tools/visual.py).
export type Row = Record<string, unknown>;

export type VisualBlock = {
  type: "status_card" | "table" | "line_chart" | "bar_chart" | "stacked_bar_chart" | "map" | "heatmap";
  title: string;
  source: string;
  fields: Record<string, unknown>;
  rows: Row[];
};

/** Long rows (category, series, value) -> one object per category with a key per series. */
export function pivot(rows: Row[], category: string, series: string, value: string) {
  const seriesNames = [...new Set(rows.map((r) => String(r[series] ?? "—")))];
  const byCat = new Map<string, Row>();
  for (const r of rows) {
    const cat = String(r[category] ?? "—");
    const row = byCat.get(cat) ?? { [category]: cat };
    const s = String(r[series] ?? "—");
    row[s] = ((row[s] as number | undefined) ?? 0) + (Number(r[value]) || 0);
    byCat.set(cat, row);
  }
  return { data: [...byCat.values()], seriesNames };
}

/** Column names in a fields value: a name, a list of names, or {field: name}. */
export function names(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(names);
  if (value && typeof value === "object" && "field" in value)
    return names((value as { field: unknown }).field);
  return [];
}

export function columnsOf(rows: Row[]): string[] {
  const seen = new Set<string>();
  for (const r of rows) for (const k of Object.keys(r)) seen.add(k);
  return [...seen];
}

const isNumber = (v: unknown) => typeof v === "number" && Number.isFinite(v);
const isDateLike = (v: unknown) =>
  typeof v === "string" && /^\d{4}-\d{2}(-\d{2})?/.test(v);

export function isNumeric(rows: Row[], col: string) {
  const vals = rows.map((r) => r[col]).filter((v) => v != null);
  return vals.length > 0 && vals.every(isNumber);
}

export function isDate(rows: Row[], col: string) {
  const vals = rows.map((r) => r[col]).filter((v) => v != null);
  return vals.length > 0 && vals.every(isDateLike);
}

/**
 * Resolves the columns a visual needs. Uses the documented keys (x, y, value, ...) when the model
 * sent them; otherwise infers them from the columns named anywhere in `fields`, then from the rows.
 */
export function resolve(block: VisualBlock) {
  const cols = columnsOf(block.rows);
  const has = (c: string) => cols.includes(c);
  const f = block.fields ?? {};
  const pick = (key: string) => names(f[key]).filter(has);
  const mentioned = [...new Set(Object.values(f).flatMap(names))].filter(has);
  const pool = mentioned.length ? mentioned : cols;
  const numeric = (c: string) => isNumeric(block.rows, c);
  const date = (c: string) => isDate(block.rows, c);
  const firstOf = (list: string[], test: (c: string) => boolean, not: string[] = []) =>
    list.find((c) => test(c) && !not.includes(c)) ??
    cols.find((c) => test(c) && !not.includes(c));

  const x = pick("x")[0] ?? firstOf(pool, date);
  const category = pick("category")[0] ?? firstOf(pool, (c) => !numeric(c) && !date(c));
  // A column counts for an inferred series only if most rows have a value.
  const dense = (c: string) => block.rows.filter((r) => r[c] != null).length >= block.rows.length / 2;
  const y = pick("y").length
    ? pick("y")
    : pool.filter((c) => numeric(c) && dense(c) && c !== x && !c.endsWith("_threshold_c"));
  const series = pick("series")[0] ?? firstOf(pool, (c) => !numeric(c) && !date(c), category ? [category] : []);
  const heatY = pick("y")[0] ?? firstOf(pool, (c) => !numeric(c), x ? [x] : []);
  const value = pick("value")[0] ?? firstOf(pool, numeric);
  // Heatmap cells: the value column if the model named one, else a count of rows.
  const heatValue = pick("value")[0] ?? mentioned.find(numeric);
  const lat = pick("lat")[0] ?? (has("lat") ? "lat" : undefined);
  const lon = pick("lon")[0] ?? (has("lon") ? "lon" : undefined);
  const label = pick("label")[0] ?? (has("asset_id") ? "asset_id" : category);
  const tableCols = pick("columns").length ? pick("columns") : mentioned.length ? mentioned : cols;

  return {
    cols, x, y, category, series, value, heatY, heatValue, lat, lon, label, tableCols,
    unit: typeof f.unit === "string" ? f.unit : undefined,
  };
}

export function fmt(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(1);
  if (Array.isArray(v)) {
    if (v.length === 0) return "—";
    return v.map((x) => (typeof x === "object" && x ? Object.values(x)[0] : x)).join(", ");
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export const label = (col: string) => col.replace(/_/g, " ");
