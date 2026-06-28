import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { QueryProvider } from "@/components/QueryProvider";
import { ThemeProvider } from "@/components/ThemeProvider";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";

const ibmPlexSans = IBM_Plex_Sans({
  weight: ["400", "500", "600", "700"],
  subsets: ["latin"],
  variable: "--font-ibm-plex-sans",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SLM Platform",
  description: "SLM Knowledge Platform — manage and push API knowledge to LLaMA 3.2",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${ibmPlexSans.variable} ${ibmPlexMono.variable}`}>
      <body>
        <QueryProvider>
          <ThemeProvider>
            <div style={{ display: "flex", height: "100vh", width: "100%", overflow: "hidden", background: "var(--bg)", color: "var(--text)" }}>
              <Sidebar />
              <main style={{ flex: 1, display: "flex", flexDirection: "column", height: "100vh", minWidth: 0 }}>
                <Topbar />
                <div style={{ flex: 1, overflow: "auto", background: "var(--bg)" }}>
                  {children}
                </div>
              </main>
            </div>
          </ThemeProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
