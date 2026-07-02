"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Pencil, Loader2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import { api, type JobDetail } from "@/lib/api";
import { useDemoMode } from "@/lib/demo";

export function JobEditDialog({ job }: { job: JobDetail }) {
  const { demoMode } = useDemoMode();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState(job.title);
  const [company, setCompany] = useState(job.company);
  const [location, setLocation] = useState(job.location);
  const [workplaceType, setWorkplaceType] = useState(job.workplace_type);
  const [seniorityLevel, setSeniorityLevel] = useState(job.seniority_level || "");
  const [roleType, setRoleType] = useState(job.role_type || "");
  const [compMin, setCompMin] = useState(job.comp_min != null ? String(job.comp_min) : "");
  const [compMax, setCompMax] = useState(job.comp_max != null ? String(job.comp_max) : "");
  const [compCurrency, setCompCurrency] = useState(job.comp_currency || "");
  const [companyHomepage, setCompanyHomepage] = useState(job.company_homepage || "");
  const [applyUrl, setApplyUrl] = useState(job.apply_url || "");
  const [jdFull, setJdFull] = useState(job.jd_full || "");

  useEffect(() => {
    if (open) {
      setTitle(job.title);
      setCompany(job.company);
      setLocation(job.location);
      setWorkplaceType(job.workplace_type);
      setSeniorityLevel(job.seniority_level || "");
      setRoleType(job.role_type || "");
      setCompMin(job.comp_min != null ? String(job.comp_min) : "");
      setCompMax(job.comp_max != null ? String(job.comp_max) : "");
      setCompCurrency(job.comp_currency || "");
      setCompanyHomepage(job.company_homepage || "");
      setApplyUrl(job.apply_url || "");
      setJdFull(job.jd_full || "");
      setError(null);
    }
  }, [open, job]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const data: Parameters<typeof api.jobs.update>[1] = {
        title: title.trim(),
        company: company.trim(),
        location: location.trim(),
        workplace_type: workplaceType.trim(),
        seniority_level: seniorityLevel.trim() || undefined,
        role_type: roleType.trim() || undefined,
        comp_currency: compCurrency.trim() || undefined,
        company_homepage: companyHomepage.trim() || undefined,
        apply_url: applyUrl.trim() || undefined,
        jd_full: jdFull,
      };
      const cmin = parseInt(compMin, 10);
      if (!isNaN(cmin)) data.comp_min = cmin;
      const cmax = parseInt(compMax, 10);
      if (!isNaN(cmax)) data.comp_max = cmax;

      await api.jobs.update(job.id, data);
      setOpen(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save changes");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant="outline" size="sm" disabled={demoMode}>
            <Pencil className="size-4" />
            Edit
          </Button>
        }
      />
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit Job</DialogTitle>
          <DialogDescription>
            Update job details and job description. Changes are saved to the database.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="details">
          <TabsList>
            <TabsTrigger value="details">Details</TabsTrigger>
            <TabsTrigger value="jd">Job Description</TabsTrigger>
          </TabsList>

          <TabsContent value="details">
            <div className="flex flex-col gap-3 max-h-[50vh] overflow-y-auto p-1">
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-title">Title</Label>
                  <Input id="edit-title" value={title} onChange={(e) => setTitle(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-company">Company</Label>
                  <Input id="edit-company" value={company} onChange={(e) => setCompany(e.target.value)} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-location">Location</Label>
                  <Input id="edit-location" value={location} onChange={(e) => setLocation(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-workplace">Workplace type</Label>
                  <Input id="edit-workplace" value={workplaceType} onChange={(e) => setWorkplaceType(e.target.value)} placeholder="remote / hybrid / onsite" />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-seniority">Seniority</Label>
                  <Input id="edit-seniority" value={seniorityLevel} onChange={(e) => setSeniorityLevel(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-role-type">Role type</Label>
                  <Input id="edit-role-type" value={roleType} onChange={(e) => setRoleType(e.target.value)} />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-comp-min">Comp min ($)</Label>
                  <Input id="edit-comp-min" type="number" value={compMin} onChange={(e) => setCompMin(e.target.value)} placeholder="e.g. 150000" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-comp-max">Comp max ($)</Label>
                  <Input id="edit-comp-max" type="number" value={compMax} onChange={(e) => setCompMax(e.target.value)} placeholder="e.g. 180000" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="edit-comp-currency">Currency</Label>
                  <Input id="edit-comp-currency" value={compCurrency} onChange={(e) => setCompCurrency(e.target.value)} placeholder="USD" />
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-homepage">Company homepage</Label>
                <Input id="edit-homepage" type="url" value={companyHomepage} onChange={(e) => setCompanyHomepage(e.target.value)} placeholder="https://example.com" />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-apply-url">Apply URL</Label>
                <Input id="edit-apply-url" type="url" value={applyUrl} onChange={(e) => setApplyUrl(e.target.value)} placeholder="https://boards.greenhouse.io/..." />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="jd">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="edit-jd-full">Job description text</Label>
              <Textarea
                id="edit-jd-full"
                value={jdFull}
                onChange={(e) => setJdFull(e.target.value)}
                className="min-h-[40vh] font-mono text-xs"
                placeholder="Paste or edit the full job description…"
              />
            </div>
          </TabsContent>
        </Tabs>

        {error && (
          <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
            {error}
          </div>
        )}

        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button onClick={handleSave} disabled={saving || demoMode}>
            {saving ? <Loader2 className="animate-spin" /> : <Save className="size-4" />}
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
