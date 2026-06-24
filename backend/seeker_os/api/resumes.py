"""Resume API routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from seeker_os.api.schemas import MessageResponse
from seeker_os.database import get_connection, json_decode

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


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
