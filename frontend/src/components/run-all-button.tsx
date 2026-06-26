"use client";

import { useState, useEffect, useRef } from "react";
import { Loader2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";

export function RunAllButton({ jobId }: { jobId: number }) {
  const [running, setRunning] = useState(false);
  const analysisDoneRef = useRef(false);
  const researchDoneRef = useRef(false);

  useEffect(() => {
    if (!running) return;

    function checkDone() {
      if (analysisDoneRef.current && researchDoneRef.current) {
        setRunning(false);
        analysisDoneRef.current = false;
        researchDoneRef.current = false;
      }
    }

    function onAnalysisComplete() {
      analysisDoneRef.current = true;
      checkDone();
    }
    function onResearchComplete() {
      researchDoneRef.current = true;
      checkDone();
    }

    window.addEventListener("analysis-complete", onAnalysisComplete);
    window.addEventListener("company-research-complete", onResearchComplete);

    const timeout = setTimeout(() => {
      setRunning(false);
      analysisDoneRef.current = false;
      researchDoneRef.current = false;
    }, 120000);

    return () => {
      window.removeEventListener("analysis-complete", onAnalysisComplete);
      window.removeEventListener("company-research-complete", onResearchComplete);
      clearTimeout(timeout);
    };
  }, [running]);

  function runAll() {
    analysisDoneRef.current = false;
    researchDoneRef.current = false;
    setRunning(true);
    window.dispatchEvent(new Event("run-all-triggered"));
  }

  return (
    <Button variant="default" size="sm" disabled={running} onClick={runAll}>
      {running ? <Loader2 className="animate-spin" /> : <Zap />}
      {running ? "Running…" : "Run AI + Research"}
    </Button>
  );
}
