"use client";

import React, { useState } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { PieChart, Sparkles } from "lucide-react";

export interface PizzaMetric {
  key: string;
  label_es: string;
  label_en: string;
  quadrant: string;
  raw_value: number;
  formatted_value: string;
  percentile: number;
  color: string;
}

export interface PizzaQuadrant {
  quadrant_key: string;
  title_es: string;
  title_en: string;
  color: string;
  metrics: PizzaMetric[];
}

export interface PizzaChartData {
  player_id: number;
  player_name: string;
  season_label?: string;
  position: string;
  position_group: string;
  total_peers: number;
  overall_percentile: number;
  quadrants: PizzaQuadrant[];
}

interface PercentilePizzaChartProps {
  data: PizzaChartData;
}

export const PercentilePizzaChart: React.FC<PercentilePizzaChartProps> = ({ data }) => {
  const { language } = usePreferences();
  const [hoveredMetric, setHoveredMetric] = useState<PizzaMetric | null>(null);

  // Flatten all 16 metrics in order
  const allMetrics: PizzaMetric[] = [];
  (data.quadrants || []).forEach((q) => {
    (q.metrics || []).forEach((m) => allMetrics.push(m));
  });

  const totalSlices = allMetrics.length || 16;
  const cx = 240;
  const cy = 240;
  const maxRadius = 180;
  const innerRadius = 38;
  const sliceAngle = (2 * Math.PI) / totalSlices;

  // Grid concentric circles for 25th, 50th, 75th, 100th percentiles
  const gridPercentiles = [25, 50, 75, 100];

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-7 shadow-xs">
      {/* Header Info */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-6 border-b border-slate-100 gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="px-2.5 py-1 text-[10px] font-black uppercase tracking-wider rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-200">
              FBref / StatsBomb Scouting Template
            </span>
            <span className="text-xs font-semibold text-slate-500">
              {language === "es" ? "Comparado contra" : "Compared vs"}{" "}
              <strong className="text-slate-800">{data.total_peers}</strong> {data.position_group}
            </span>
          </div>
          <h2 className="text-2xl font-black text-slate-900 tracking-tight mt-1.5 flex items-center gap-2">
            <span>{data.player_name}</span>
            <span className="text-sm font-semibold text-slate-400">({data.season_label || "2023-24"})</span>
          </h2>
        </div>

        {/* Global Percentile Badge */}
        <div className="flex items-center gap-3 bg-amber-50 border border-amber-200 rounded-2xl px-4 py-2 shadow-2xs">
          <div>
            <div className="text-[10px] font-extrabold uppercase text-amber-800 tracking-wider">
              {language === "es" ? "Percentil Global" : "Overall Percentile"}
            </div>
            <div className="text-xl font-black text-amber-900 font-mono">
              {data.overall_percentile?.toFixed(1) ?? "75.0"}
              <span className="text-xs font-normal text-amber-600">/100</span>
            </div>
          </div>
          <div className="w-9 h-9 rounded-xl bg-amber-200/60 border border-amber-300 flex items-center justify-center font-bold text-amber-800">
            ★
          </div>
        </div>
      </div>

      {/* Main Chart Area */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center mt-6">
        {/* SVG Radial Pizza Wheel (7 cols) */}
        <div className="lg:col-span-7 flex flex-col items-center justify-center relative">
          <svg viewBox="0 0 480 480" className="w-full max-w-[460px] h-auto drop-shadow-sm select-none">
            {/* Concentric Grid Rings */}
            {gridPercentiles.map((p) => {
              const r = innerRadius + ((maxRadius - innerRadius) * p) / 100;
              return (
                <g key={`grid-ring-${p}`}>
                  <circle
                    cx={cx}
                    cy={cy}
                    r={r}
                    fill="none"
                    stroke="#E2E8F0"
                    strokeWidth="1.2"
                    strokeDasharray={p === 100 ? "none" : "4,4"}
                  />
                  <text
                    x={cx + 4}
                    y={cy - r + 11}
                    fill="#94A3B8"
                    fontSize="9"
                    fontWeight="700"
                    fontFamily="monospace"
                  >
                    {p}
                  </text>
                </g>
              );
            })}

            {/* Slices / Petals */}
            {allMetrics.map((metric, idx) => {
              const startAngle = idx * sliceAngle - Math.PI / 2;
              const endAngle = (idx + 1) * sliceAngle - Math.PI / 2;
              const pctl = Math.max(metric.percentile, 5);
              const rSlice = innerRadius + ((maxRadius - innerRadius) * pctl) / 100;

              const x1_in = cx + innerRadius * Math.cos(startAngle);
              const y1_in = cy + innerRadius * Math.sin(startAngle);
              const x2_in = cx + innerRadius * Math.cos(endAngle);
              const y2_in = cy + innerRadius * Math.sin(endAngle);

              const x1_out = cx + rSlice * Math.cos(startAngle);
              const y1_out = cy + rSlice * Math.sin(startAngle);
              const x2_out = cx + rSlice * Math.cos(endAngle);
              const y2_out = cy + rSlice * Math.sin(endAngle);

              const pathData = [
                `M ${x1_in} ${y1_in}`,
                `L ${x1_out} ${y1_out}`,
                `A ${rSlice} ${rSlice} 0 0 1 ${x2_out} ${y2_out}`,
                `L ${x2_in} ${y2_in}`,
                `A ${innerRadius} ${innerRadius} 0 0 0 ${x1_in} ${y1_in}`,
                "Z",
              ].join(" ");

              const isHovered = hoveredMetric?.key === metric.key;

              return (
                <g key={metric.key} className="cursor-pointer transition-all duration-200">
                  <path
                    d={pathData}
                    fill={metric.color}
                    fillOpacity={isHovered ? 1 : 0.82}
                    stroke="#FFFFFF"
                    strokeWidth="1.5"
                    onMouseEnter={() => setHoveredMetric(metric)}
                    onMouseLeave={() => setHoveredMetric(null)}
                    className="hover:opacity-100 transition-opacity"
                  />
                  {/* Spoke Line */}
                  <line
                    x1={cx + innerRadius * Math.cos(startAngle)}
                    y1={cy + innerRadius * Math.sin(startAngle)}
                    x2={cx + maxRadius * Math.cos(startAngle)}
                    y2={cy + maxRadius * Math.sin(startAngle)}
                    stroke="#CBD5E1"
                    strokeWidth="0.8"
                    strokeDasharray="2 2"
                  />
                </g>
              );
            })}

            {/* Inner Hub Circle */}
            <circle cx={cx} cy={cy} r={innerRadius - 2} fill="#F8FAFC" stroke="#E2E8F0" strokeWidth="2" />
            <text
              x={cx}
              y={cy - 4}
              textAnchor="middle"
              fill="#0F172A"
              fontSize="12"
              fontWeight="900"
            >
              {data.position}
            </text>
            <text
              x={cx}
              y={cy + 10}
              textAnchor="middle"
              fill="#64748B"
              fontSize="8"
              fontWeight="700"
              fontFamily="monospace"
            >
              NBA
            </text>
          </svg>

          {/* Hover Detail Card */}
          {hoveredMetric ? (
            <div className="mt-4 p-3 bg-slate-50 border border-slate-200 rounded-2xl text-center max-w-xs shadow-xs animate-in fade-in">
              <span className="text-[10px] uppercase font-bold text-slate-400">
                {language === "es" ? hoveredMetric.label_es : hoveredMetric.label_en}
              </span>
              <div className="flex items-center justify-center gap-2 mt-1">
                <span className="text-sm font-bold text-slate-800">{hoveredMetric.formatted_value}</span>
                <span
                  className="text-xs font-black font-mono px-2 py-0.5 rounded-full text-white"
                  style={{ backgroundColor: hoveredMetric.color }}
                >
                  {hoveredMetric.percentile}th %
                </span>
              </div>
            </div>
          ) : (
            <div className="mt-4 text-xs font-semibold text-slate-400 italic">
              {language === "es" ? "Pasa el cursor sobre un sector para ver métricas" : "Hover over a slice to inspect details"}
            </div>
          )}
        </div>

        {/* 4 Quadrants Summary Cards (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          {(data.quadrants || []).map((quad) => (
            <div
              key={quad.quadrant_key}
              className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 transition-all hover:bg-slate-50 hover:border-slate-300"
            >
              <div className="flex items-center justify-between pb-2 border-b border-slate-200/60">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: quad.color }} />
                  <h3 className="text-xs font-extrabold text-slate-900 uppercase tracking-wider">
                    {language === "es" ? quad.title_es : quad.title_en}
                  </h3>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 mt-3">
                {(quad.metrics || []).map((m) => (
                  <div
                    key={m.key}
                    onMouseEnter={() => setHoveredMetric(m)}
                    onMouseLeave={() => setHoveredMetric(null)}
                    className="p-2 rounded-xl bg-white border border-slate-200/80 hover:border-slate-400 transition-all cursor-pointer flex items-center justify-between shadow-2xs"
                  >
                    <div>
                      <div className="text-[10px] font-bold text-slate-600 truncate max-w-[100px]">
                        {language === "es" ? m.label_es : m.label_en}
                      </div>
                      <div className="text-xs font-bold text-slate-900 font-mono">{m.formatted_value}</div>
                    </div>
                    <span
                      className="text-[10px] font-black font-mono px-1.5 py-0.5 rounded text-white shrink-0 ml-1"
                      style={{ backgroundColor: m.color }}
                    >
                      {m.percentile}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
