"""Resume API routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from seeker_os.api.schemas import ResumeParseResult, ContactInfoSchema

from seeker_os.api.schemas import MessageResponse
from seeker_os.database import get_connection, json_decode

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


class MasterResumeInfo(BaseModel):
    """Info about the master resume."""
    path: str
    exists: bool
    size_bytes: int = 0
    format: str = ""  # 'md', 'docx', 'pdf'
    text_preview: str = ""  # first 500 chars


@router.get("/master", response_model=MasterResumeInfo)
def get_master_resume_info():
    """Get info about the configured master resume file."""
    from seeker_os.config import Settings

    settings = Settings()
    if not settings.profile or not settings.profile.resume:
        raise HTTPException(status_code=404, detail="No resume config in profile.yml")

    master_path = Path(settings.profile.resume.master_path).expanduser()
    fmt = master_path.suffix.lstrip(".").lower() if master_path.suffix else ""

    if not master_path.exists():
        return MasterResumeInfo(
            path=str(master_path),
            exists=False,
            format=fmt,
        )

    # Read preview (md only for speed; docx/pdf need extraction)
    preview = ""
    if fmt == "md":
        try:
            text = master_path.read_text(encoding="utf-8")
            preview = text[:500]
        except Exception:
            pass

    return MasterResumeInfo(
        path=str(master_path),
        exists=True,
        size_bytes=master_path.stat().st_size,
        format=fmt,
        text_preview=preview,
    )


@router.post("/master/upload", response_model=MasterResumeInfo)
async def upload_master_resume(file: UploadFile = File(...)):
    """Upload a master resume file (md, docx, or pdf).

    Saves the file to the configured master_path in profile.yml.
    If the path has no extension, the uploaded file's extension is appended.
    """
    from seeker_os.config import Settings

    settings = Settings()
    if not settings.profile or not settings.profile.resume:
        raise HTTPException(status_code=404, detail="No resume config in profile.yml")

    master_path = Path(settings.profile.resume.master_path).expanduser()

    # Determine format from uploaded filename
    uploaded_name = file.filename or "resume.md"
    ext = Path(uploaded_name).suffix.lower()
    if ext not in (".md", ".docx", ".pdf"):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}. Use .md, .docx, or .pdf")

    # If the configured path has no extension or a different one, use the uploaded extension
    if master_path.suffix.lower() != ext:
        master_path = master_path.with_suffix(ext)

    # Ensure parent dir exists
    master_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the file
    content = await file.read()
    master_path.write_bytes(content)

    fmt = ext.lstrip(".")
    preview = ""
    if fmt == "md":
        try:
            preview = content.decode("utf-8")[:500]
        except Exception:
            pass

    return MasterResumeInfo(
        path=str(master_path),
        exists=True,
        size_bytes=len(content),
        format=fmt,
        text_preview=preview,
    )


@router.post("/parse", response_model=ResumeParseResult)
def parse_master_resume():
    """Parse the master resume using LLM to extract structured profile data.

    Extracts: contact info, experience years, current title, key skills,
    suggested filter parameters (title patterns, comp floor), and a summary.
    """
    from seeker_os.config import Settings

    settings = Settings()
    if not settings.profile or not settings.profile.resume:
        raise HTTPException(status_code=404, detail="No resume config in profile.yml")

    master_path = Path(settings.profile.resume.master_path).expanduser()
    if not master_path.exists():
        raise HTTPException(status_code=404, detail=f"Master resume not found at {master_path}")

    # Read resume text
    fmt = master_path.suffix.lstrip(".").lower()
    resume_text = ""
    if fmt == "md":
        resume_text = master_path.read_text(encoding="utf-8")
    elif fmt == "docx":
        try:
            from seeker_os.resume.extract import extract_docx_text
            resume_text = extract_docx_text(master_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to extract DOCX: {e}")
    elif fmt == "pdf":
        try:
            from seeker_os.resume.extract import extract_pdf_text
            resume_text = extract_pdf_text(master_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to extract PDF: {e}")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported resume format: {fmt}")

    if not resume_text or len(resume_text) < 100:
        raise HTTPException(status_code=400, detail="Resume text too short or empty")

    # Use LLM to extract structured data
    try:
        from seeker_os.llm.router import ModelRouter
        router = ModelRouter(settings)
        system_prompt = """You are a resume parser. Extract structured information from the resume text.
Return ONLY valid JSON (no markdown, no code fences) with this exact schema:
{
  "contact": {
    "name": "Full Name",
    "email": "email@example.com",
    "phone": "phone number or empty string",
    "location": "City, ST",
    "urls": {"github": "url or empty", "linkedin": "url or empty", "portfolio": "url or empty", "other": "url or empty"}
  },
  "experience_years": 25,
  "current_title": "Most recent or current job title",
  "key_skills": ["Go", "Kubernetes", "Terraform", ...],
  "suggested_title_positive": ["sre", "site reliability", "platform engineer", ...],
  "suggested_comp_floor": 150000,
  "summary": "One paragraph summary of the candidate's profile"
}

Rules:
- experience_years: integer, estimate from work history if not explicit
- suggested_title_positive: lowercase substrings that would match this person's target roles in job titles
- suggested_comp_floor: integer USD, infer from current/target comp or experience level
- key_skills: top 10-15 technologies, tools, and methodologies
- If a field can't be determined, use empty string, empty list, or null"""

        response = router.generate(
            task="resume_parsing",
            system_prompt=system_prompt,
            user_prompt=f"Parse this resume:\n\n{resume_text[:8000]}",
            temperature=0.3,
            max_tokens=2000,
        )

        # Parse the JSON response
        import re
        text = response.text.strip()
        # Strip markdown code fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        data = json.loads(text)

        result = ResumeParseResult(
            contact=ContactInfoSchema(**data.get("contact", {})),
            experience_years=data.get("experience_years"),
            current_title=data.get("current_title", ""),
            key_skills=data.get("key_skills", []),
            suggested_title_positive=data.get("suggested_title_positive", []),
            suggested_comp_floor=data.get("suggested_comp_floor"),
            summary=data.get("summary", ""),
        )

        # Save extracted data to config files
        _save_parsed_to_config(settings, result)

        return result

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"LLM returned invalid JSON: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resume parsing failed: {e}")


def _save_parsed_to_config(settings, result: ResumeParseResult) -> None:
    """Save parsed resume data to profile.yml and filters.yml."""
    from seeker_os.config_writer import write_profile, write_filters

    profile = settings.profile
    filters_cfg = settings.filters

    # Update profile with extracted contact info
    if result.contact.name and result.contact.name != "Your Name":
        profile.user.name = result.contact.name
    if result.contact.email and "@" in result.contact.email:
        profile.user.email = result.contact.email
    if result.contact.location:
        profile.user.location = result.contact.location
    if result.contact.phone:
        if not hasattr(profile.user, "phone") or not profile.user.phone:
            profile.user.phone = result.contact.phone
    # Update contact URLs
    if hasattr(profile, "resume") and profile.resume:
        urls = []
        for url_key in ["portfolio", "linkedin", "github", "other"]:
            url_val = getattr(result.contact.urls, url_key, None) if result.contact.urls else None
            if url_val:
                urls.append(url_val)
        if urls:
            profile.resume.contact_urls = urls

    # Update experience years
    if result.experience_years and hasattr(profile, "experience"):
        profile.experience.years = result.experience_years
        if result.experience_years >= 10:
            profile.experience.anchor_phrase = f"{result.experience_years}+ years"

    # Update comp from suggestion.
    # Keep the three values sane: floor <= target <= stretch.
    # If the suggested floor exceeds the current target, bump target up to
    # floor + 10% so the scoring modifier still makes sense.
    if result.suggested_comp_floor and hasattr(profile, "comp"):
        new_floor = result.suggested_comp_floor
        profile.comp.floor = new_floor
        # Ensure target stays above floor
        if profile.comp.target and profile.comp.target < new_floor:
            profile.comp.target = int(new_floor * 1.10)
        # Ensure stretch stays above target
        if profile.comp.stretch and profile.comp.stretch < (profile.comp.target or new_floor):
            profile.comp.stretch = int((profile.comp.target or new_floor) * 1.30)

    write_profile(profile)

    # Update filters with suggested title patterns and comp floor
    if filters_cfg:
        if result.suggested_title_positive:
            # Merge with existing positive patterns (avoid duplicates)
            existing = set(filters_cfg.title_filters.positive)
            merged = list(existing) + [t for t in result.suggested_title_positive if t not in existing]
            filters_cfg.title_filters.positive = merged

        if result.suggested_comp_floor:
            filters_cfg.filters.comp_floor = result.suggested_comp_floor

        write_filters(filters_cfg)


class ResumeGenerateRequest(BaseModel):
    """POST /api/resumes/generate."""
    job_id: int
    task: str = "resume_generation_standard"  # or "resume_generation_high_value"
    temperature: float = 0.7
    max_tokens: int | None = 16000


class ResumeSummary(BaseModel):
    """Resume summary for list views."""
    id: int
    job_id: int
    task: str = ""
    provider: str = ""
    model: str = ""
    validation_passed: bool = False
    validation_violations: list[dict] = []
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    generated_at: str = ""
    markdown_path: str = ""
    pdf_path: str | None = None
    docx_path: str | None = None


class ResumeDetail(BaseModel):
    """Full resume detail."""
    id: int
    job_id: int
    job_title: str = ""
    job_company: str = ""
    task: str = ""
    provider: str = ""
    model: str = ""
    resume_text: str = ""
    validation_passed: bool = False
    validation_violations: list[dict] = []
    validation_checked_at: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    generated_at: str = ""
    markdown_path: str = ""
    pdf_path: str | None = None
    docx_path: str | None = None


@router.get("", response_model=list[ResumeSummary])
def list_resumes(job_id: int | None = Query(None), limit: int = Query(50, ge=1, le=200)):
    """List generated resumes."""
    from seeker_os.resume.generator import list_resumes as _list
    resumes = _list(job_id=job_id, limit=limit)
    return [
        ResumeSummary(
            id=r["id"],
            job_id=r["job_id"],
            task=r["task"],
            provider=r["provider"],
            model=r["model"],
            validation_passed=r["validation_passed"],
            validation_violations=r["validation_violations"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            latency_ms=r["latency_ms"],
            generated_at=r["generated_at"],
            markdown_path=r["markdown_path"],
            pdf_path=r.get("pdf_path"),
            docx_path=r.get("docx_path"),
        )
        for r in resumes
    ]


@router.get("/{resume_id}", response_model=ResumeDetail)
def get_resume(resume_id: int):
    """Get full resume detail."""
    from seeker_os.resume.generator import get_resume as _get
    r = _get(resume_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")
    return ResumeDetail(**r)


@router.post("/generate", response_model=dict)
def generate_resume(body: ResumeGenerateRequest):
    """Generate a tailored resume for a job."""
    from seeker_os.config import Settings
    from seeker_os.resume.generator import generate_resume as _generate

    settings = Settings()
    try:
        result = _generate(
            settings=settings,
            job_id=body.job_id,
            task=body.task,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.post("/{resume_id}/validate", response_model=dict)
def revalidate_resume(resume_id: int):
    """Re-run accuracy validation on a stored resume."""
    from seeker_os.config import Settings
    from seeker_os.resume.validator import AccuracyValidator

    settings = Settings()
    validator = AccuracyValidator(settings)
    try:
        result = validator.revalidate(resume_id)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{resume_id}/pdf")
def download_pdf(resume_id: int):
    """Download the PDF version of a resume."""
    db = get_connection()
    row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")

    pdf_path = row["pdf_path"]
    if pdf_path and Path(pdf_path).exists():
        return FileResponse(pdf_path, media_type="application/pdf", filename=Path(pdf_path).name)

    # Try to generate PDF on the fly
    from seeker_os.resume.export import export_pdf
    md_path = Path(row["markdown_path"]) if row["markdown_path"] else None
    if md_path and md_path.exists():
        output = export_pdf(md_path)
        if output:
            # Save path to DB
            db = get_connection()
            db.execute("UPDATE resumes SET pdf_path=? WHERE id=?", (str(output), resume_id))
            db.commit()
            db.close()
            return FileResponse(str(output), media_type="application/pdf", filename=output.name)

    raise HTTPException(status_code=404, detail="PDF not available — install weasyprint for PDF export")


@router.get("/{resume_id}/markdown")
def download_markdown(resume_id: int):
    """Download the markdown source of a resume."""
    db = get_connection()
    row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")

    md_path = row["markdown_path"]
    if md_path and Path(md_path).exists():
        return FileResponse(md_path, media_type="text/markdown", filename=Path(md_path).name)

    raise HTTPException(status_code=404, detail="Markdown file not found")


@router.get("/{resume_id}/docx")
def download_docx(resume_id: int):
    """Download the DOCX version of a resume."""
    db = get_connection()
    row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")

    docx_path = row["docx_path"]
    if docx_path and Path(docx_path).exists():
        return FileResponse(docx_path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=Path(docx_path).name)

    # Try to generate DOCX on the fly
    from seeker_os.resume.export import export_docx
    md_path = Path(row["markdown_path"]) if row["markdown_path"] else None
    if md_path and md_path.exists():
        output = export_docx(md_path)
        if output:
            db = get_connection()
            db.execute("UPDATE resumes SET docx_path=? WHERE id=?", (str(output), resume_id))
            db.commit()
            db.close()
            return FileResponse(str(output), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=output.name)

    raise HTTPException(status_code=404, detail="DOCX not available — install python-docx for DOCX export")
