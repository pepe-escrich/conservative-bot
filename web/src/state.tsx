// Contexto global: fuente de datos activa (paper o un run de backtest).

import { createContext, useContext, useState, ReactNode } from "react";
import { Source } from "./api";

interface SourceState {
  source: Source;
  setSource: (s: Source) => void;
}

const SourceContext = createContext<SourceState>({
  source: { kind: "paper" },
  setSource: () => {},
});

export function SourceProvider({ children }: { children: ReactNode }) {
  const [source, setSource] = useState<Source>({ kind: "paper" });
  return (
    <SourceContext.Provider value={{ source, setSource }}>{children}</SourceContext.Provider>
  );
}

export const useSource = () => useContext(SourceContext);
