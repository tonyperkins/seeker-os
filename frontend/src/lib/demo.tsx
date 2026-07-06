"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";

interface DemoModeContextValue {
  demoMode: boolean;
  loading: boolean;
}

const DemoModeContext = createContext<DemoModeContextValue>({
  demoMode: false,
  loading: true,
});

export function DemoModeProvider({ children }: { children: ReactNode }) {
  const [demoMode, setDemoMode] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/demo-mode")
      .then((res) => res.json())
      .then((data) => {
        setDemoMode(Boolean(data.demo_mode));
        setLoading(false);
      })
      .catch(() => {
        setDemoMode(false);
        setLoading(false);
      });
  }, []);

  return (
    <DemoModeContext.Provider value={{ demoMode, loading }}>
      {children}
    </DemoModeContext.Provider>
  );
}

export function useDemoMode() {
  return useContext(DemoModeContext);
}
