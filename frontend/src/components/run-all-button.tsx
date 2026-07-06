"use client";

import { useState, useEffect, useRef } from "react";
import { Loader2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";

export function RunAllButton({ jobId }: { jobId: number }) {
  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState("");
  const analysisDoneRef = useRef(false);
  const researchDoneRef = useRef(false);
  const researchStartedRef = useRef(false);

  useEffect(() => {
    if (!running) return;

    function checkDone() {
      if (analysisDoneRef.current && researchDoneRef.current) {
        setRunning(false);
        setPhase("");
        analysisDoneRef.current = false;
        researchDoneRef.current = false;
        researchStartedRef.current = false;
      }
    }

    function onResearchComplete() {
      researchDoneRef.current = true;
      // Research is done — now trigger analysis so it can use the dossier
      setPhase("Analyzing…");
      window.dispatchEvent(new Event("run-analysis-triggered"));
      checkDone();
    }

    function onResearchFailed() {
      // Research failed — still run analysis without the dossier
      researchDoneRef.current = true;
      setPhase("Analyzing…");
      window.dispatchEvent(new Event("run-analysis-triggered"));
      checkDone();
    }

    function onAnalysisComplete() {
      analysisDoneRef.current = true;
      checkDone();
    }

    window.addEventListener("analysis-complete", onAnalysisComplete);
    window.addEventListener("company-research-complete", onResearchComplete);
    window.addEventListener("company-research-failed", onResearchFailed);

    const timeout = setTimeout(() => {
      setRunning(false);
      setPhase("");
      analysisDoneRef.current = false;
      researchDoneRef.current = false;
      researchStartedRef.current = false;
    }, 180000);

    return () => {
      window.removeEventListener("analysis-complete", onAnalysisComplete);
      window.removeEventListener("company-research-complete", onResearchComplete);
      window.removeEventListener("company-research-failed", onResearchFailed);
      clearTimeout(timeout);
    };
  }, [running]);

  function runAll() {
    analysisDoneRef.current = false;
    researchDoneRef.current = false;
    researchStartedRef.current = false;
    setPhase("Researching…");
    setRunning(true);
    // Only trigger research — analysis will be triggered after research completes
    window.dispatchEvent(new Event("run-research-triggered"));
  }

  return (
    <Button variant="default" size="sm" disabled={running} onClick={runAll}>
      {running ? <Loader2 className="animate-spin" /> : <Zap />}
      {running ? phase : "Run AI + Research"}
    </Button>
  );
}
