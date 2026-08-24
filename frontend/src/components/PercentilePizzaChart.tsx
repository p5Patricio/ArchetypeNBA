"use client";

import React, { useState } from "react";
import { usePreferences } from "@/context/PreferencesContext";


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
  data.quadrants.forEach((q) => {
    q.metrics.forEach((m) => allMetrics.push(m));
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
    <div className="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 backdrop-blur-xl shadow-2xl relative overflow-hidden">
      {/* Background Neon Brand Glow */}
      <div className="absolute -top-24 -right-24 w-72 h-72 bg-indigo-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-24 -left-24 w-72 h-72 bg-orange-600/10 rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-6 border-b border-white/10 gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="px-2.5 py-1 text-xs font-semibold uppercase tracking-wider rounded-md bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
              FBref / StatsBomb Model
            </span>
            <span className="text-xs text-gray-400">
              {language === "es" ? `Comparado vs ${data.total_peers} ${data.position_group}s` : `Compared vs ${data.total_peers} ${data.position_group}s`}
            </span>
          </div>
          <h2 className="text-2xl font-bold text-white tracking-wide mt-1.5 flex items-center gap-2">
            <span>{data.player_name}</span>
            <span className="text-sm font-normal text-gray-400">({data.season_label || "Active"})</span>
          </h2>
        </div>

        {/* Overall Rating Badge */}
        <div className="flex items-center gap-3 bg-white/5 border border-white/10 rounded-xl px-4 py-2">
          <div className="text-right">
            <div className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
              {language === "es" ? "Percentil Global" : "Overall Percentile"}
            </div>
            <div className="text-xl font-black text-amber-400">
              {data.overall_percentile.toFixed(1)}
              <span className="text-xs font-normal text-gray-400">/100</span>
            </div>
          </div>
          <div className="w-10 h-10 rounded-lg bg-amber-500/20 border border-amber-500/40 flex items-center justify-center font-bold text-amber-300">
            ★
          </div>
        </div>
      </div>

      {/* Main Chart Area */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center mt-6">
        {/* SVG Radial Pizza Wheel (7 cols) */}
        <div className="lg:col-span-7 flex flex-col items-center justify-center relative">
          <svg viewBox="0 0 480 480" className="w-full max-w-[460px] h-auto drop-shadow-2xl">
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
                    stroke="#374151"
                    strokeWidth="1"
                    strokeDasharray={p === 100 ? "none" : "3,3"}
                    opacity="0.6"
                  />
                  <text
                    x={cx + 4}
                    y={cy - r + 11}
                    fill="#9CA3AF"
                    fontSize="9"
                    fontWeight="600"
                    opacity="0.75"
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
                <g key={metric.key} className="cursor-pointer transition-all duration-300">
                  <path
                    d={pathData}
                    fill={metric.color}
                    fillOpacity={isHovered ? 0.95 : 0.72}
                    stroke="#111827"
                    strokeWidth="1.5"
                    onMouseEnter={() => setHoveredMetric(metric)}
                    onMouseLeave={() => setHoveredMetric(null)}
                    className="hover:scale-[1.02] origin-center transition-transform"
                  />
                  {/* Spoke Line */}
                  <line
                    x1={cx + innerRadius * Math.cos(startAngle)}
                    y1={cy + innerRadius * Math.sin(startAngle)}
                    x2={cx + maxRadius * Math.cos(startAngle)}
                    y2={cy + maxRadius * Math.sin(startAngle)}
                    stroke="#1F2937"
                    strokeWidth="1"
                    opacity="0.7"
                  />
                </g>
              );
            })}

            {/* Inner Hub Circle */}
            <circle cx={cx} cy={cy} r={innerRadius - 2} fill="#1F2937" stroke="#374151" strokeWidth="2" />
            <text
              x={cx}
              y={cy - 4}
              textAnchor="middle"
              fill="#F3F4F6"
              fontSize="12"
              fontWeight="bold"
            >
              {data.position}
            </text>
            <text
              x={cx}
              y={cy + 10}
              textAnchor="middle"
              fill="#9CA3AF"
              fontSize="8"
              fontWeight="500"
            >
              PERCENTILE
            </text>
          </svg>

          {/* Hover Floating Tooltip Preview */}
          {hoveredMetric ? (
            <div className="mt-2 text-center bg-gray-900/90 border border-white/10 px-4 py-2 rounded-xl backdrop-blur-md">
              <span className="text-xs text-gray-400 font-medium">
                {language === "es" ? hoveredMetric.label_es : hoveredMetric.label_en}:
              </span>
              <span className="ml-2 text-sm font-bold text-white">{hoveredMetric.formatted_value}</span>
              <span
                className="ml-2 px-2 py-0.5 text-xs font-bold rounded-full"
                style={{ backgroundColor: `${hoveredMetric.color}30`, color: hoveredMetric.color }}
              >
                {hoveredMetric.percentile} Pctl
              </span>
            </div>
          ) : (
            <p className="mt-2 text-xs text-gray-500 italic">
              {language === "es" ? "Pasa el cursor sobre cualquier sección para explorar la métrica" : "Hover over any slice to inspect metric details"}
            </p>
          )}
        </div>

        {/* 4 Quadrants Legend & Metrics Breakdown (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          {data.quadrants.map((quad) => (
            <div
              key={quad.quadrant_key}
              className="bg-black/30 border border-white/5 rounded-xl p-3.5 hover:border-white/15 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span
                    className="w-3 h-3 rounded-full shadow-sm"
                    style={{ backgroundColor: quad.color }}
                  />
                  <h4 className="text-sm font-bold text-gray-200">
                    {language === "es" ? quad.title_es : quad.title_en}
                  </h4>
                </div>
              </div>

              {/* Quadrant Metrics Bar List */}
              <div className="space-y-1.5">
                {quad.metrics.map((m) => (
                  <div
                    key={m.key}
                    onMouseEnter={() => setHoveredMetric(m)}
                    onMouseLeave={() => setHoveredMetric(null)}
                    className={`flex items-center justify-between p-1.5 rounded-lg text-xs cursor-pointer transition-all ${
                      hoveredMetric?.key === m.key ? "bg-white/10" : "hover:bg-white/5"
                    }`}
                  >
                    <span className="text-gray-300 font-medium truncate max-w-[170px]">
                      {language === "es" ? m.label_es : m.label_en}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-400 font-mono">{m.formatted_value}</span>
                      <span
                        className="font-bold font-mono px-1.5 py-0.5 rounded text-[11px] min-w-[38px] text-right"
                        style={{
                          backgroundColor: `${m.color}25`,
                          color: m.color,
                        }}
                      >
                        {Math.round(m.percentile)}
                      </span>
                    </div>
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
