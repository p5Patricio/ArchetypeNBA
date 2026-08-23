import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { PreferencesProvider } from "@/context/PreferencesContext";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ArchetypeNBA — Sports Science & Tactical Scouting",
  description: "Plataforma de scouting avanzado, clustering K-Means multitemporada, radares 7D y métricas de impacto en la NBA.",
  icons: {
    icon: "/archetypenba-logo.jpg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased bg-[#f8fafc] text-slate-900`}>
        <PreferencesProvider>{children}</PreferencesProvider>
      </body>
    </html>
  );
}
