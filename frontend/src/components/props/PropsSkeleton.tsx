"use client";

import React from "react";

export function PropsSkeleton() {
  return (
    <div
      className="space-y-8 animate-pulse"
      role="status"
      aria-label="Cargando proyecciones de props"
    >
      {/* Meta Metrics Cards Skeleton */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs space-y-2.5"
          >
            <div className="h-3 w-20 bg-slate-200 rounded-md" />
            <div className="h-5 w-28 bg-slate-300 rounded-lg" />
          </div>
        ))}
      </div>

      {/* Filter Bar Skeleton */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-2 overflow-hidden">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-8 w-24 bg-slate-200 rounded-xl shrink-0" />
            ))}
          </div>
          <div className="h-6 w-36 bg-slate-200 rounded-full" />
        </div>
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-3 border-t border-slate-100">
          <div className="h-8 w-full sm:w-80 bg-slate-200 rounded-xl" />
          <div className="h-8 w-44 bg-slate-200 rounded-xl" />
        </div>
      </div>

      {/* Cards Grid Skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div
            key={i}
            className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs flex flex-col justify-between space-y-4"
          >
            <div className="space-y-4">
              {/* Header: Avatar, Name, Badge, Recommendation */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="h-11 w-11 rounded-xl bg-slate-200 shrink-0" />
                  <div className="space-y-1.5">
                    <div className="h-4 w-28 bg-slate-300 rounded-md" />
                    <div className="flex items-center gap-1.5">
                      <div className="h-3 w-10 bg-slate-200 rounded-md" />
                      <div className="h-3 w-14 bg-slate-200 rounded-md" />
                    </div>
                  </div>
                </div>
                <div className="h-6 w-24 bg-slate-200 rounded-xl" />
              </div>

              {/* Sportsbook vs Model Matrix */}
              <div className="rounded-xl bg-slate-50 border border-slate-100 p-3.5 space-y-3">
                <div className="flex items-center justify-between border-b border-slate-200/60 pb-2">
                  <div className="space-y-1">
                    <div className="h-2.5 w-16 bg-slate-200 rounded" />
                    <div className="h-4 w-24 bg-slate-300 rounded" />
                  </div>
                  <div className="space-y-1 text-right">
                    <div className="h-2.5 w-16 bg-slate-200 rounded ml-auto" />
                    <div className="h-4 w-12 bg-slate-300 rounded ml-auto" />
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 pt-1">
                  {[1, 2, 3].map((col) => (
                    <div key={col} className="space-y-1 text-center">
                      <div className="h-2.5 w-12 bg-slate-200 rounded mx-auto" />
                      <div className="h-4 w-10 bg-slate-300 rounded mx-auto" />
                    </div>
                  ))}
                </div>

                <div className="space-y-1 pt-1">
                  <div className="h-2 w-full bg-slate-200 rounded-full" />
                </div>
              </div>

              {/* Edge & EV Pills */}
              <div className="grid grid-cols-2 gap-2.5">
                <div className="h-14 rounded-xl bg-slate-100 p-2.5" />
                <div className="h-14 rounded-xl bg-slate-100 p-2.5" />
              </div>

              {/* Kelly Stake */}
              <div className="h-8 rounded-xl bg-slate-100" />

              {/* Monte Carlo Range */}
              <div className="h-4 w-full bg-slate-100 rounded" />

              {/* AI Context Box */}
              <div className="pt-2 border-t border-slate-100">
                <div className="h-16 rounded-xl bg-slate-100 p-3" />
              </div>
            </div>
          </div>
        ))}
      </div>
      <span className="sr-only">Cargando proyecciones de props...</span>
    </div>
  );
}
