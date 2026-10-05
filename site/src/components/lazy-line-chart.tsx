"use client";

import { type ComponentProps, lazy, Suspense } from "react";
import type { LineChart as Chart } from "./line-chart";

const LineChart = lazy(() => import("./line-chart").then((m) => ({ default: m.LineChart })));

type Props = ComponentProps<typeof Chart>;

/** LineChart loaded on first render; a box of the chart's height holds its place until then. */
export function LazyLineChart(props: Props) {
  const h = props.height ?? (props.compact ? 150 : 340);
  return (
    <Suspense
      fallback={
        <div className="chart chart-pending" style={{ height: h }} aria-busy="true">
          <span className="visually-hidden">Loading…</span>
        </div>
      }
    >
      <LineChart {...props} />
    </Suspense>
  );
}
