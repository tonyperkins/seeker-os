"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import {
  Upload,
  Sparkles,
  SlidersHorizontal,
  Play,
  CheckCircle2,
  Loader2,
  ArrowRight,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { MasterResumeUpload } from "@/components/master-resume-upload";
import { api, type MasterResumeInfo } from "@/lib/api";

export function SetupGuide({
  resumeInfo,
  isProfilePlaceholder,
  totalJobs,
}: {
  resumeInfo: MasterResumeInfo | null;
  isProfilePlaceholder: boolean;
  totalJobs: number;
}) {
  const [info, setInfo] = useState<MasterResumeInfo | null>(resumeInfo);
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  const onUploaded = useCallback(() => {
    // Refresh resume info after upload
    api.resumes.getMaster().then(setInfo).catch(() => {});
  }, []);

  const handleParse = useCallback(async () => {
    setParsing(true);
    setParseError(null);
    try {
      await api.resumes.parse();
      setParsed(true);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "Failed to parse resume");
    } finally {
      setParsing(false);
    }
  }, []);

  // Determine step completion
  const step1Done = info?.exists ?? false;
  const step2Done = parsed;
  const step3Done = !isProfilePlaceholder;
  const step4Done = totalJobs > 0;

  const steps = [
    {
      icon: Upload,
      title: "Upload your master resume",
      description: "Upload your resume (.md, .docx, or .pdf). This is the source for all tailored resume generation.",
      done: step1Done,
      action: step1Done ? null : "upload",
    },
    {
      icon: Sparkles,
      title: "Parse your resume",
      description: "Extract contact info, experience, skills, and suggested filter parameters automatically.",
      done: step2Done,
      action: step1Done && !step2Done ? "parse" : null,
    },
    {
      icon: SlidersHorizontal,
      title: "Review your profile & filters",
      description: "Check the extracted data, adjust your filter parameters, and add any free-form instructions.",
      done: step3Done,
      action: step2Done && !step3Done ? "settings" : (!step1Done ? null : "settings"),
    },
    {
      icon: Play,
      title: "Run the pipeline",
      description: "Execute the full discovery → filter → JD fetch → scoring pipeline to find matching jobs.",
      done: step4Done,
      action: step3Done && !step4Done ? "pipeline" : null,
    },
  ];

  const allDone = step1Done && step3Done && step4Done;

  if (allDone) return null;

  const currentStep = steps.find((s) => !s.done);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-5 text-primary" />
          Welcome to Seeker OS
        </CardTitle>
        <CardDescription>
          Let&apos;s get you set up. Follow these steps to start finding your next role.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4">
          {/* Step list */}
          <div className="flex flex-col gap-2">
            {steps.map((step, i) => {
              const Icon = step.icon;
              const isCurrent = step === currentStep;
              return (
                <div
                  key={i}
                  className={`flex items-start gap-3 rounded-lg border p-3 transition-colors ${
                    isCurrent ? "border-primary/40 bg-primary/5" : "border-border"
                  }`}
                >
                  <div className="flex size-7 shrink-0 items-center justify-center rounded-full">
                    {step.done ? (
                      <CheckCircle2 className="size-5 text-emerald-500" />
                    ) : (
                      <div className={`flex size-6 items-center justify-center rounded-full text-xs font-medium ${
                        isCurrent ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                      }`}>
                        {i + 1}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-1 flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <Icon className={`size-4 ${step.done ? "text-emerald-500" : "text-muted-foreground"}`} />
                      <span className={`text-sm font-medium ${step.done ? "text-muted-foreground line-through" : ""}`}>
                        {step.title}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">{step.description}</p>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Current step action */}
          {currentStep?.action === "upload" && (
            <div className="rounded-lg border border-border p-4">
              <MasterResumeUpload onUploaded={onUploaded} bare />
            </div>
          )}

          {currentStep?.action === "parse" && (
            <div className="flex flex-col gap-3 rounded-lg border border-border p-4">
              <p className="text-sm text-muted-foreground">
                Your resume is uploaded. Now let&apos;s extract your profile data.
              </p>
              <Button onClick={handleParse} disabled={parsing} size="lg">
                {parsing ? <Loader2 className="animate-spin" /> : <Sparkles />}
                {parsing ? "Parsing Resume..." : "Parse Resume"}
              </Button>
              {parseError && (
                <p className="text-xs text-destructive">{parseError}</p>
              )}
              {parsed && (
                <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="size-4" />
                  Resume parsed! Review your profile in Settings.
                </div>
              )}
            </div>
          )}

          {currentStep?.action === "settings" && (
            <Link href="/settings" className="inline-flex">
              <Button variant="outline" size="lg" className="w-full">
                <SlidersHorizontal />
                Go to Settings to Review & Edit
                <ArrowRight />
              </Button>
            </Link>
          )}

          {currentStep?.action === "pipeline" && (
            <div className="rounded-lg border border-border p-4 text-center">
              <p className="text-sm text-muted-foreground mb-3">
                You&apos;re all set! Run the pipeline from the dashboard below to start discovering jobs.
              </p>
              <ArrowRight className="size-5 mx-auto text-muted-foreground animate-bounce" />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
