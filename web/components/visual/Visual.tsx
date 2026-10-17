"use client";

import dynamic from "next/dynamic";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fmt, label, resolve, type Row, type VisualBlock } from "./spec";

const VisualMap = dynamic(() => import("./VisualMap"), {
  ssr: false,
  loading: () => <div className="h-80 animate-pulse rounded-lg bg-muted" />,
});

const COLORS = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];

export function Visual({ block }: { block: VisualBlock }) {
  return (
    <figure className="my-3 w-full rounded-xl border bg-card p-4 shadow-sm">
      <figcaption className="mb-3 flex items-baseline justify-between gap-2">
        <span className="font-semibold">{block.title}</span>
        <span className="text-xs text-muted-foreground">
          {block.rows.length} rows · {block.source}
        </span>
      </figcaption>
      {block.rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No rows.</p>
      ) : (
        <Body block={block} />
      )}
    </figure>
  );
}

function Body({ block }: { block: VisualBlock }) {
  const r = resolve(block);
  switch (block.type) {
    case "status_card":
      return <StatusCard row={block.rows[0]} />;
    case "line_chart":
      return r.x && r.y.length ? <LineView rows={block.rows} x={r.x} y={r.y} unit={r.unit} /> : <Table rows={block.rows} cols={r.tableCols} />;
    case "bar_chart":
      return r.category && r.value ? <BarView rows={block.rows} x={r.category} y={r.value} unit={r.unit} /> : <Table rows={block.rows} cols={r.tableCols} />;
    case "heatmap":
      return r.x && r.heatY ? <Heatmap rows={block.rows} x={r.x} y={r.heatY} value={r.heatValue} /> : <Table rows={block.rows} cols={r.tableCols} />;
    case "map":
      return r.lat && r.lon ? <VisualMap rows={block.rows} lat={r.lat} lon={r.lon} label={r.label} /> : <Table rows={block.rows} cols={r.tableCols} />;
    default:
      return <Table rows={block.rows} cols={r.tableCols} />;
  }
}

function Table({ rows, cols }: { rows: Row[]; cols: string[] }) {
  return (
    <div className="max-h-96 overflow-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-muted">
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 text-left font-medium capitalize whitespace-nowrap">{label(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t">
              {cols.map((c) => (
                <td key={c} className="px-3 py-1.5 align-top">{fmt(row[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Red dots where the row says the well was not producing. */
function ProducingDot(props: { cx?: number; cy?: number; payload?: Row; stroke?: string }) {
  const { cx, cy, payload, stroke } = props;
  if (cx == null || cy == null) return null;
  const down = payload?.is_producing === false;
  return <circle cx={cx} cy={cy} r={down ? 5 : 3} fill={down ? "#ef4444" : stroke} stroke="white" strokeWidth={1} />;
}

function LineView({ rows, x, y, unit }: { rows: Row[]; x: string; y: string[]; unit?: string }) {
  const marksDown = rows.some((r) => r.is_producing === false);
  return (
    <>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
          <XAxis dataKey={x} fontSize={12} />
          <YAxis fontSize={12} unit={unit ? ` ${unit}` : undefined} />
          <Tooltip />
          <Legend formatter={(v) => label(String(v))} />
          {y.map((col, i) => (
            <Line key={col} dataKey={col} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={<ProducingDot />} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
      {marksDown && <p className="mt-1 text-xs text-muted-foreground">Red dots: not producing.</p>}
    </>
  );
}

function BarView({ rows, x, y, unit }: { rows: Row[]; x: string; y: string; unit?: string }) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
        <XAxis dataKey={x} fontSize={12} />
        <YAxis fontSize={12} unit={unit ? ` ${unit}` : undefined} />
        <Tooltip />
        <Bar dataKey={y} name={label(y)} fill={COLORS[0]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function Heatmap({ rows, x, y, value }: { rows: Row[]; x: string; y: string; value?: string }) {
  // Daily dates are grouped by month, so raw event rows still give a readable grid.
  const xKey = (r: Row) => {
    const v = String(r[x]);
    return /^\d{4}-\d{2}-\d{2}/.test(v) ? v.slice(0, 7) : v;
  };
  const xs = [...new Set(rows.map(xKey))].sort();
  const ys = [...new Set(rows.map((r) => String(r[y])))].sort();
  const cell = new Map<string, number>();
  for (const r of rows) {
    const k = `${r[y]}|${xKey(r)}`;
    cell.set(k, (cell.get(k) ?? 0) + (value ? Number(r[value]) || 0 : 1));
  }
  const max = Math.max(1, ...cell.values());
  const rowTotal = (yy: string) => xs.reduce((s, xx) => s + (cell.get(`${yy}|${xx}`) ?? 0), 0);
  return (
    <div className="overflow-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th />
            {xs.map((xx) => <th key={xx} className="px-1 pb-1 font-normal text-muted-foreground">{xx}</th>)}
            <th className="px-2 pb-1 font-medium">Total</th>
          </tr>
        </thead>
        <tbody>
          {ys.map((yy) => (
            <tr key={yy}>
              <th className="pr-2 text-left font-medium whitespace-nowrap">{yy}</th>
              {xs.map((xx) => {
                const v = cell.get(`${yy}|${xx}`);
                const a = v ? 0.12 + 0.88 * (v / max) : 0;
                return (
                  <td key={xx} className="h-9 min-w-11 border border-background text-center"
                      style={{ background: v ? `rgba(37,99,235,${a})` : undefined, color: a > 0.55 ? "white" : undefined }}
                      title={`${yy} · ${xx}: ${v ?? 0} ${value ? label(value) : "rows"}`}>
                    {v != null ? fmt(v) : ""}
                  </td>
                );
              })}
              <td className="px-2 text-center font-semibold">{fmt(rowTotal(yy))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-xs text-muted-foreground">Cells: {value ? label(value) : "number of records"}.</p>
    </div>
  );
}

type Note = { note_id?: string; text?: string; author_name?: string; valid_from?: string; valid_to?: string | null };

function StatusCard({ row }: { row: Row }) {
  const producing = row.is_producing;
  const notes = (Array.isArray(row.current_notes) ? row.current_notes : []) as Note[];
  const repairs = Array.isArray(row.open_repairs) ? row.open_repairs : [];
  const shown = new Set(["asset_id", "is_producing", "well_type", "area_name", "temp_delta_c", "producing_threshold_c",
    "inspection_id", "inspected_at", "inspector_name", "method", "inspection_notes", "current_notes", "open_repairs"]);
  const rest = Object.entries(row).filter(([k, v]) => !shown.has(k) && v != null && !(Array.isArray(v) && v.length === 0));
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-lg font-semibold">{fmt(row.asset_id)}</span>
        {producing != null && (
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${producing ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
            {producing ? "Producing" : "Not producing"}
          </span>
        )}
        <span className="text-muted-foreground">{[row.well_type, row.area_name].filter(Boolean).join(" · ")}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat k="Temp delta" v={row.temp_delta_c != null ? `${fmt(row.temp_delta_c)} °C` : "—"}
              hint={row.producing_threshold_c != null ? `threshold ${fmt(row.producing_threshold_c)} °C` : undefined} />
        <Stat k="Last inspection" v={fmt(row.inspection_id)} hint={typeof row.inspected_at === "string" ? row.inspected_at.slice(0, 10) : undefined} />
        <Stat k="Inspector" v={fmt(row.inspector_name)} hint={row.method ? String(row.method) : undefined} />
      </div>
      {row.inspection_notes != null && <p className="italic text-muted-foreground">“{String(row.inspection_notes)}”</p>}
      {notes.length > 0 && (
        <ul className="space-y-1">
          {notes.map((n, i) => (
            <li key={n.note_id ?? i} className="rounded-md bg-muted px-3 py-2">
              <span className="font-mono text-xs">{n.note_id}</span> {n.text}
              {n.author_name && <span className="text-muted-foreground"> — {n.author_name}</span>}
            </li>
          ))}
        </ul>
      )}
      {repairs.length > 0 && <p><span className="font-medium">Open repairs:</span> {fmt(repairs)}</p>}
      {rest.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-3">
          {rest.map(([k, v]) => (
            <div key={k}><dt className="inline capitalize">{label(k)}: </dt><dd className="inline text-foreground">{fmt(v)}</dd></div>
          ))}
        </dl>
      )}
    </div>
  );
}

function Stat({ k, v, hint }: { k: string; v: string; hint?: string }) {
  return (
    <div className="rounded-lg border px-3 py-2">
      <div className="text-xs text-muted-foreground">{k}</div>
      <div className="font-semibold">{v}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
