"use client";

import React, { useState, useEffect } from "react";
import { Power, CheckCircle2, AlertTriangle, RefreshCw, X } from "lucide-react";
import { shutdownServices } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";

interface ShutdownModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ShutdownModal({ isOpen, onClose }: ShutdownModalProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  const [loading, setLoading] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Reset state when opening
  useEffect(() => {
    if (isOpen) {
      setLoading(false);
      setStopped(false);
      setErrorMessage(null);
    }
  }, [isOpen]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !loading && !stopped) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, loading, stopped, onClose]);

  if (!isOpen) return null;

  const handleConfirmShutdown = async () => {
    setLoading(true);
    setErrorMessage(null);

    try {
      await shutdownServices();
      setStopped(true);
    } catch (err: unknown) {
      // If server dies immediately, the connection drop might manifest as a network error,
      // which actually means the server shut down successfully!
      console.warn("Shutdown request ended with network disconnect (expected during termination):", err);
      setStopped(true);
    } finally {
      setLoading(false);
    }
  };

  const handleCloseTab = () => {
    window.close();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-200">
      <div
        className="relative w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-2xl transition-all"
        role="dialog"
        aria-modal="true"
      >
        {/* Top Close Button (only when not stopping or stopped) */}
        {!loading && !stopped && (
          <button
            onClick={onClose}
            className="absolute top-5 right-5 rounded-xl p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
            aria-label="Cerrar modal"
          >
            <X className="h-5 w-5" />
          </button>
        )}

        {!stopped ? (
          /* Confirmation State */
          <div className="space-y-6">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-rose-100 text-rose-600 shadow-inner">
                <Power className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-lg font-black text-slate-900">
                  {isEs ? "Detener Servicios Locales" : "Stop Local Services"}
                </h3>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Puertos 38920 (Web) & 38921 (API)
                </p>
              </div>
            </div>

            <div className="rounded-2xl border border-rose-100 bg-rose-50/60 p-4 space-y-2 text-xs text-rose-900 leading-relaxed">
              <div className="flex items-center gap-2 font-bold text-rose-700">
                <AlertTriangle className="h-4 w-4 shrink-0 text-rose-600" />
                <span>
                  {isEs ? "¿Cerrar los procesos en segundo plano?" : "Terminate background processes?"}
                </span>
              </div>
              <p className="text-slate-600">
                {isEs
                  ? "Esta acción finalizará por completo el servidor Backend y la aplicación Frontend, liberando la memoria RAM y los puertos de tu PC."
                  : "This will terminate both the Backend and Frontend servers, completely releasing RAM and ports on your PC."}
              </p>
              <p className="text-slate-500 text-[11px]">
                {isEs
                  ? "💡 Podrás volver a iniciarlos cuando quieras ejecutando el script de inicio o al encender tu PC."
                  : "💡 You can restart anytime by running the startup script or rebooting Windows."}
              </p>
            </div>

            {errorMessage && (
              <p className="text-xs text-rose-600 font-bold bg-rose-50 p-3 rounded-xl border border-rose-200">
                {errorMessage}
              </p>
            )}

            {/* Action Buttons */}
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={onClose}
                disabled={loading}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 hover:bg-slate-50 transition-colors disabled:opacity-50 cursor-pointer"
              >
                {isEs ? "Cancelar" : "Cancel"}
              </button>

              <button
                type="button"
                onClick={handleConfirmShutdown}
                disabled={loading}
                className="rounded-xl bg-gradient-to-r from-rose-600 to-red-600 px-5 py-2.5 text-xs font-black text-white shadow-md hover:from-rose-500 hover:to-red-500 hover:shadow-rose-600/20 active:scale-[0.98] transition-all inline-flex items-center gap-2 disabled:opacity-60 cursor-pointer"
              >
                {loading ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 animate-spin text-white" />
                    <span>{isEs ? "Deteniendo servicios..." : "Stopping services..."}</span>
                  </>
                ) : (
                  <>
                    <Power className="h-3.5 w-3.5 text-white" />
                    <span>{isEs ? "Sí, Detener Servicios" : "Yes, Stop Services"}</span>
                  </>
                )}
              </button>
            </div>
          </div>
        ) : (
          /* Success / Stopped State */
          <div className="space-y-6 text-center py-2 animate-in zoom-in-95 duration-200">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-600 shadow-inner">
              <CheckCircle2 className="h-9 w-9" />
            </div>

            <div className="space-y-2">
              <h3 className="text-xl font-black text-slate-900">
                {isEs ? "Servicios Detenidos Exitosamente" : "Services Stopped Successfully"}
              </h3>
              <p className="text-xs sm:text-sm text-slate-600 max-w-sm mx-auto leading-relaxed">
                {isEs
                  ? "Los procesos en segundo plano se han cerrado y los puertos 38920 y 38921 quedaron liberados. Ya podés cerrar esta pestaña."
                  : "Background processes have been terminated and ports 38920 and 38921 are released. You may now close this tab."}
              </p>
            </div>

            <div className="pt-2 flex flex-col items-center gap-2">
              <button
                type="button"
                onClick={handleCloseTab}
                className="w-full rounded-xl bg-slate-900 px-5 py-3 text-xs font-black text-white shadow-sm hover:bg-slate-800 transition-all cursor-pointer"
              >
                {isEs ? "Cerrar Pestaña del Navegador" : "Close Browser Tab"}
              </button>
              <span className="text-[11px] text-slate-400 font-medium">
                {isEs ? "o presioná Ctrl + W" : "or press Ctrl + W"}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
