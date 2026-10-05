"use client";

import {
  type KeyboardEvent,
  type PointerEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { formatNumber } from "@/lib/units";

export type ChartSeries = {
  id: string;
  label: string;
  /** CSS colour, normally a series token like var(--s1). */
  color: string;
  values: number[];
  /** Spacing of an evenly sampled series starting at 0 (Mach tables). */
  step?: number;
  /** Explicit x of each value (axis columns, envelope speeds); wins over `step`. */
  x?: number[];
};

type Props = {
  series: ChartSeries[];
  title: string;
  xLabel?: string;
  /** Unit shown after values in the tooltip. */
  yUnit?: string | null;
  height?: number;
  compact?: boolean;
};

const xsOf = (s: ChartSeries) => s.x ?? s.values.map((_, i) => i * (s.step ?? 1));

export function niceTicks(min: number, max: number, count: number): number[] {
  if (min === max) return [min];
  const span = max - min;
  const raw = span / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 1e-6; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setWidth(Math.max(200, Math.round(el.getBoundingClientRect().width)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** Mach-indexed line chart: thin lines, recessive grid, crosshair + tooltip, keyboard steppable. */
export function LineChart({
  series,
  title,
  xLabel = "Mach",
  yUnit,
  height,
  compact = false,
}: Props) {
  const [wrapRef, width] = useWidth<HTMLDivElement>(compact ? 300 : 720);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const h = height ?? (compact ? 150 : 340);
  const pad = compact
    ? { top: 8, right: 10, bottom: 22, left: 44 }
    : { top: 14, right: series.length <= 4 ? 96 : 20, bottom: 40, left: 60 };
  const innerW = width - pad.left - pad.right;
  const innerH = h - pad.top - pad.bottom;

  const { xMin, xMax, yMin, yMax, xTicks, yTicks, xGrid } = useMemo(() => {
    const all = series.flatMap((s) => s.values);
    const xsAll = series.flatMap(xsOf);
    // Evenly sampled series (Mach tables) start at 0; explicit axes start at their first value.
    const x0 = series.some((s) => s.x) ? Math.min(...xsAll) : Math.min(0, ...xsAll);
    const xm = Math.max(x0 + (series.some((s) => s.x) ? 1e-9 : 0.2), ...xsAll);
    let lo = Math.min(...all);
    let hi = Math.max(...all);
    if (lo === hi) {
      lo -= Math.abs(lo) * 0.1 || 1;
      hi += Math.abs(hi) * 0.1 || 1;
    }
    const padY = (hi - lo) * 0.08;
    const yt = niceTicks(lo - padY, hi + padY, compact ? 3 : 5);
    return {
      xMin: x0,
      xMax: xm,
      yMin: Math.min(lo - padY, yt[0] ?? lo),
      yMax: Math.max(hi + padY, yt[yt.length - 1] ?? hi),
      xTicks: niceTicks(x0, xm, compact ? 4 : 8),
      yTicks: yt,
      xGrid: [...new Set(xsAll)].sort((a, b) => a - b),
    };
  }, [series, compact]);

  const sx = (x: number) => pad.left + ((x - xMin) / (xMax - xMin)) * innerW;
  const sy = (y: number) => pad.top + (1 - (y - yMin) / (yMax - yMin)) * innerH;

  const valueAt = (s: ChartSeries, x: number) => {
    const xs = xsOf(s);
    const i = xs.findIndex((v) => Math.abs(v - x) < 1e-6);
    return i >= 0 ? (s.values[i] ?? null) : null;
  };

  const nearest = (x: number) =>
    xGrid.reduce((best, v) => (Math.abs(v - x) < Math.abs(best - x) ? v : best), xGrid[0] ?? 0);

  const onPointer = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left;
    setHoverX(nearest(xMin + ((px - pad.left) / innerW) * (xMax - xMin)));
  };

  const onKey = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const dir = event.key === "ArrowRight" ? 1 : -1;
    setHoverX((x) => {
      if (x === null) return (dir > 0 ? xGrid[0] : xGrid[xGrid.length - 1]) ?? null;
      const i = xGrid.indexOf(x);
      return xGrid[Math.min(xGrid.length - 1, Math.max(0, i + dir))] ?? x;
    });
  };

  const fmtX = (x: number) => formatNumber(Number(x.toFixed(3)));
  const tooltipLeft = hoverX === null ? 0 : sx(hoverX);
  const flip = tooltipLeft > width * 0.6;

  // Direct labels at line ends, nudged apart so they do not collide.
  const endLabels = useMemo(() => {
    if (compact || series.length > 4) return [];
    const labels = series
      .map((s) => {
        const last = s.values[s.values.length - 1] ?? 0;
        const xs = xsOf(s);
        return { id: s.id, label: s.label, x: xs[xs.length - 1] ?? 0, y: last };
      })
      .map((l) => ({ ...l, py: pad.top + (1 - (l.y - yMin) / (yMax - yMin)) * innerH }))
      .sort((a, b) => a.py - b.py);
    for (let i = 1; i < labels.length; i++) {
      const prev = labels[i - 1];
      const cur = labels[i];
      if (prev && cur && cur.py - prev.py < 14) cur.py = prev.py + 14;
    }
    return labels;
  }, [series, compact, yMin, yMax, innerH, pad.top]);

  return (
    <div className="chart" ref={wrapRef}>
      <svg
        width={width}
        height={h}
        viewBox={`0 0 ${width} ${h}`}
        role="img"
        aria-label={`${title} by ${xLabel}. Arrow keys read values.`}
        tabIndex={0}
        onPointerMove={onPointer}
        onPointerLeave={() => setHoverX(null)}
        onKeyDown={onKey}
        onBlur={() => setHoverX(null)}
      >
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line className="gridline" x1={pad.left} x2={width - pad.right} y1={sy(t)} y2={sy(t)} />
            <text className="tick-label" x={pad.left - 6} y={sy(t)} dy="0.32em" textAnchor="end">
              {formatNumber(t, 3)}
            </text>
          </g>
        ))}
        <line
          className="axis"
          x1={pad.left}
          x2={width - pad.right}
          y1={pad.top + innerH}
          y2={pad.top + innerH}
        />
        {xTicks.map((t) => (
          <text
            key={`x${t}`}
            className="tick-label"
            x={sx(t)}
            y={pad.top + innerH + 14}
            textAnchor="middle"
          >
            {fmtX(t)}
          </text>
        ))}
        {compact ? null : (
          <text className="axis-title" x={pad.left + innerW / 2} y={h - 6} textAnchor="middle">
            {xLabel}
          </text>
        )}
        {series.map((s) => (
          <path
            key={s.id}
            className="series-line"
            stroke={s.color}
            data-series={s.id}
            d={xsOf(s)
              .map(
                (x, i) =>
                  `${i === 0 ? "M" : "L"}${sx(x).toFixed(1)},${sy(s.values[i] ?? 0).toFixed(1)}`,
              )
              .join("")}
          />
        ))}
        {endLabels.map((l) => (
          <text key={`l${l.id}`} className="direct-label" x={sx(l.x) + 8} y={l.py} dy="0.32em">
            {l.label}
          </text>
        ))}
        {hoverX !== null ? (
          <g>
            <line
              className="crosshair"
              x1={sx(hoverX)}
              x2={sx(hoverX)}
              y1={pad.top}
              y2={pad.top + innerH}
            />
            {series.map((s) => {
              const v = valueAt(s, hoverX);
              return v === null ? null : (
                <circle
                  key={s.id}
                  className="dot"
                  cx={sx(hoverX)}
                  cy={sy(v)}
                  r={4.5}
                  fill={s.color}
                />
              );
            })}
          </g>
        ) : null}
      </svg>
      {hoverX !== null ? (
        <div
          className="chart-tooltip"
          role="status"
          style={{
            top: pad.top,
            ...(flip ? { right: width - tooltipLeft + 12 } : { left: tooltipLeft + 12 }),
          }}
        >
          <div className="chart-tooltip-title">
            {xLabel} {fmtX(hoverX)}
          </div>
          {series.map((s) => {
            const v = valueAt(s, hoverX);
            return (
              <div className="chart-tooltip-row" key={s.id}>
                <span className="swatch" style={{ background: s.color }} />
                <span>{s.label}</span>
                <span className="v">
                  {v === null ? "—" : formatNumber(v)}
                  {v !== null && yUnit ? ` ${yUnit}` : ""}
                </span>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export { SERIES_COLORS } from "./chart-colors";
