"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";

type Theme = "light" | "dark";
interface ThemeCtx { theme: Theme; toggle: () => void; }
const Ctx = createContext<ThemeCtx>({ theme: "light", toggle: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    try {
      const saved = localStorage.getItem("slm_theme") as Theme | null;
      if (saved === "dark" || saved === "light") setTheme(saved);
    } catch {}
  }, []);

  function toggle() {
    setTheme((t) => {
      const next = t === "light" ? "dark" : "light";
      try { localStorage.setItem("slm_theme", next); } catch {}
      return next;
    });
  }

  return (
    <Ctx.Provider value={{ theme, toggle }}>
      <div className={theme === "dark" ? "dark" : ""} style={{ display: "contents" }}>
        {children}
      </div>
    </Ctx.Provider>
  );
}

export function useTheme() { return useContext(Ctx); }
