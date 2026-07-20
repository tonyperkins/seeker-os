"""Resume API routes."""

from __future__ import annotations

import json
import logging
import queue
import queue as queue_module
import threading
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from seeker_os.api.schemas import ContactInfoSchema, MessageResponse, ResumeParseResult
from seeker_os.database import get_connection
from seeker_os.llm.json_utils import extract_json_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/resumes", tags=["resumes"])

MAX_RESUME_BYTES = 10 * 1024 * 1024

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class MasterResumeInfo(BaseModel):
    """Info about the master resume."""
    path: str
    exists: bool
    size_bytes: int = 0
    format: str = ""  # 'md', 'docx', 'pdf'
    text_preview: str = ""  # first 500 chars


class MasterResumeContentResponse(BaseModel):
    content: str


class PendingReviewCountResponse(BaseModel):
    count: int


@router.get("/master", response_model=MasterResumeInfo)
def get_master_resume_info():
    """Get info about the configured master resume file."""
    from seeker_os.config import get_settings

    settings = get_settings()
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
        except (OSError, UnicodeError):
            logger.warning("Could not read markdown master-resume preview", exc_info=True)

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
    from seeker_os.config import get_settings

    settings = get_settings()
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
    if len(content) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_RESUME_BYTES // (1024 * 1024)} MB maximum size")
    master_path.write_bytes(content)

    fmt = ext.lstrip(".")
    preview = ""
    if fmt == "md":
        try:
            preview = content.decode("utf-8")[:500]
        except UnicodeError:
            logger.warning("Uploaded markdown resume is not valid UTF-8", exc_info=True)

    return MasterResumeInfo(
        path=str(master_path),
        exists=True,
        size_bytes=len(content),
        format=fmt,
        text_preview=preview,
    )


@router.get("/master/content", response_model=MasterResumeContentResponse)
def get_master_resume_content():
    """Get the full text content of the master resume (markdown only)."""
    from seeker_os.config import get_settings

    settings = get_settings()
    if not settings.profile or not settings.profile.resume:
        raise HTTPException(status_code=404, detail="No resume config in profile.yml")

    master_path = Path(settings.profile.resume.master_path).expanduser()
    if not master_path.exists():
        raise HTTPException(status_code=404, detail=f"Master resume not found at {master_path}")

    fmt = master_path.suffix.lstrip(".").lower()
    if fmt != "md":
        raise HTTPException(status_code=400, detail=f"Content editing is only supported for markdown resumes (got .{fmt})")

    return {"content": master_path.read_text(encoding="utf-8")}


class MasterResumeContentUpdate(BaseModel):
    content: str


@router.put("/master/content", response_model=MessageResponse)
def update_master_resume_content(body: MasterResumeContentUpdate):
    """Update the full text content of the master resume (markdown only)."""
    from seeker_os.config import get_settings

    settings = get_settings()
    if not settings.profile or not settings.profile.resume:
        raise HTTPException(status_code=404, detail="No resume config in profile.yml")

    master_path = Path(settings.profile.resume.master_path).expanduser()
    fmt = master_path.suffix.lstrip(".").lower()
    if fmt != "md":
        raise HTTPException(status_code=400, detail=f"Content editing is only supported for markdown resumes (got .{fmt})")

    master_path.parent.mkdir(parents=True, exist_ok=True)
    master_path.write_text(body.content, encoding="utf-8")

    return MessageResponse(message="Master resume updated")


@router.post("/parse", response_model=ResumeParseResult)
def parse_master_resume():
    """Parse the master resume using LLM to extract structured profile data.

    Extracts: contact info, experience years, current title, key skills,
    suggested filter parameters (title patterns, comp floor), and a summary.
    """
    from seeker_os.config import get_settings

    settings = get_settings()
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
        except Exception:
            logger.exception("DOCX extraction failed")
            raise HTTPException(status_code=500, detail="Failed to extract DOCX — see server logs for details")
    elif fmt == "pdf":
        try:
            from seeker_os.resume.extract import extract_pdf_text
            resume_text = extract_pdf_text(master_path)
        except Exception:
            logger.exception("PDF extraction failed")
            raise HTTPException(status_code=500, detail="Failed to extract PDF — see server logs for details")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported resume format: {fmt}")

    if not resume_text or len(resume_text) < 100:
        raise HTTPException(status_code=400, detail="Resume text too short or empty")

    # Use LLM to extract structured data
    try:
        from seeker_os.llm.router import ModelRouter
        router = ModelRouter(settings)
        system_prompt = (_PROMPTS_DIR / "resume_parser_system.txt").read_text(encoding="utf-8")

        response = router.generate(
            task="resume_parsing",
            system_prompt=system_prompt,
            user_prompt=f"Parse this resume:\n\n{resume_text[:8000]}",
            temperature=0.3,
        )

        # Parse the JSON response
        text = extract_json_text(response.text)
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

    except json.JSONDecodeError:
        logger.exception("LLM returned invalid JSON during resume parsing")
        raise HTTPException(status_code=500, detail="LLM returned invalid JSON — see server logs for details")
    except Exception as e:
        logger.exception("Resume parsing failed")
        raise HTTPException(status_code=500, detail=f"Resume parsing failed: {e}")


def _save_parsed_to_config(settings, result: ResumeParseResult) -> None:
    """Save parsed resume data to profile.yml and filters.yml."""
    from seeker_os.config_writer import write_filters, write_profile

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

    # Update filters with suggested title patterns
    if filters_cfg:
        if result.suggested_title_positive:
            # Merge with existing positive patterns (avoid duplicates)
            existing = set(filters_cfg.title_filters.positive)
            merged = list(existing) + [t for t in result.suggested_title_positive if t not in existing]
            filters_cfg.title_filters.positive = merged

        write_filters(filters_cfg)


class ResumeGenerateRequest(BaseModel):
    """POST /api/resumes/generate."""
    job_id: int
    task: str = "resume_generation_standard"  # or "resume_generation_high_value"
    temperature: float = 0.7
    max_tokens: int | None = None  # None = resolve from config/defaults


class ResumeManualCreate(BaseModel):
    """POST /api/resumes/manual — save a hand-built markdown resume."""
    job_id: int
    resume_text: str


class ResumeSummary(BaseModel):
    """Resume summary for list views."""
    id: int
    job_id: int
    job_company: str = ""
    task: str = ""
    provider: str = ""
    model: str = ""
    validation_passed: bool = False
    validation_violations: list[dict] = []
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float | None = None
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


@router.get("/pending-count", response_model=PendingReviewCountResponse)
def pending_review_count():
    """Count of resumes with validation_passed = false (docs to review)."""
    from seeker_os.database import get_connection
    db = get_connection()
    try:
        count = db.execute(
            "SELECT COUNT(*) as c FROM resumes WHERE validation_passed = 0"
        ).fetchone()["c"]
        return {"count": count}
    finally:
        db.close()


def _build_pricing_map() -> dict[tuple[str, str], tuple[float | None, float | None]]:
    """Build a (provider, model) → (input_price, output_price) map.

    Merges YAML config pricing (providers.yml) with auto-fetched pricing
    from provider model caches (Kilo, OpenRouter, etc.), matching the
    logic in the spend analytics endpoint.
    """
    from seeker_os.config import get_settings
    from seeker_os.llm.cache import get_cached_pricing

    settings = get_settings()
    pricing: dict[tuple[str, str], tuple[float | None, float | None]] = {}

    # 1. YAML config pricing (providers.yml)
    if settings.providers:
        for prov in settings.providers.providers:
            for model in prov.models:
                pricing[(prov.id, model.id)] = (
                    model.input_price_per_mtok,
                    model.output_price_per_mtok,
                )

    # 2. Auto-fetched pricing from model cache (fills in missing prices)
    #    Uses get_cached_pricing which ignores TTL staleness — pricing doesn't
    #    go stale the way model availability does.
    if settings.providers:
        for prov in settings.providers.providers:
            cached = get_cached_pricing(prov.id)
            for model_id, (auto_in, auto_out) in cached.items():
                key = (prov.id, model_id)
                yaml_in, yaml_out = pricing.get(key, (None, None))
                in_price = yaml_in if yaml_in is not None else auto_in
                out_price = yaml_out if yaml_out is not None else auto_out
                pricing[key] = (in_price, out_price)

    return pricing


def _estimate_cost(
    provider: str,
    model: str,
    in_tok: int,
    out_tok: int,
    pricing: dict[tuple[str, str], tuple[float | None, float | None]],
) -> float | None:
    """Estimate cost from token counts and pricing map. Returns None if no pricing."""
    in_price, out_price = pricing.get((provider, model), (None, None))
    # Fuzzy match: handle version-pinned IDs like 'qwen/qwen3.7-max-20260520'
    # where the cache has the base ID 'qwen/qwen3.7-max'
    if in_price is None and out_price is None:
        for (p, m), (pin, pout) in pricing.items():
            if p != provider:
                continue
            if model.startswith(m + "-") or m.startswith(model + "-"):
                in_price, out_price = pin, pout
                break
    if in_price is None and out_price is None:
        return None
    cost = 0.0
    if in_price is not None:
        cost += in_tok / 1_000_000 * in_price
    if out_price is not None:
        cost += out_tok / 1_000_000 * out_price
    return cost


RESUME_SORT_EXPRESSIONS: dict[str, str] = {
    "generated_at": "r.generated_at",
    "id": "r.id",
    "job_company": "LOWER(COALESCE(j.company, ''))",
    "provider": "LOWER(COALESCE(r.provider, ''))",
    "model": "LOWER(COALESCE(r.model, ''))",
    "tokens": "(r.input_tokens + r.output_tokens)",
    "latency_ms": "r.latency_ms",
}


@router.get("", response_model=list[ResumeSummary])
def list_resumes(
    job_id: int | None = Query(None),
    search: str | None = Query(None, description="Free-text search across company, provider, model, task"),
    sort_by: str | None = Query(None, description="Sort field"),
    order: str = Query("desc", description="Sort direction: asc or desc"),
    limit: int = Query(50, ge=1, le=200),
):
    """List generated resumes with optional search and sorting."""
    from seeker_os.resume.generator import list_resumes as _list
    resumes = _list(job_id=job_id, limit=limit, search=search, sort_by=sort_by, order=order)
    pricing = _build_pricing_map()
    return [
        ResumeSummary(
            id=r["id"],
            job_id=r["job_id"],
            job_company=r.get("job_company", ""),
            task=r["task"],
            provider=r["provider"],
            model=r["model"],
            validation_passed=r["validation_passed"],
            validation_violations=r["validation_violations"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            estimated_cost=_estimate_cost(
                r["provider"], r["model"], r["input_tokens"], r["output_tokens"], pricing,
            ),
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


class ResumeTextUpdate(BaseModel):
    """PUT /api/resumes/{id} — update resume text."""
    resume_text: str


@router.put("/{resume_id}", response_model=MessageResponse)
def update_resume_text(resume_id: int, body: ResumeTextUpdate):
    """Update the text of a stored resume (inline edit). Also updates the markdown file."""
    db = get_connection()
    row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")

    now = datetime.now(UTC).isoformat()

    # Update the markdown file on disk if it exists
    md_path = row["markdown_path"]
    if md_path and Path(md_path).exists():
        Path(md_path).write_text(body.resume_text, encoding="utf-8")

    # Update the DB row
    db.execute(
        "UPDATE resumes SET resume_text = ?, updated_at = ? WHERE id = ?",
        (body.resume_text, now, resume_id),
    )
    db.commit()
    db.close()
    return MessageResponse(message=f"Resume {resume_id} updated")


@router.delete("/{resume_id}", response_model=MessageResponse)
def delete_resume(resume_id: int):
    """Delete a resume from the DB and remove associated files from disk."""
    db = get_connection()
    row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")

    # Remove files from disk
    for col in ("markdown_path", "pdf_path", "docx_path"):
        p = row[col]
        if p:
            path = Path(p)
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass  # File may be locked or already gone

    db.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
    db.commit()
    db.close()
    return MessageResponse(message=f"Resume {resume_id} deleted")


@router.post("/generate", response_model=dict)
def generate_resume(body: ResumeGenerateRequest):
    """Generate a tailored resume for a job."""
    from seeker_os.config import get_settings
    from seeker_os.resume.generator import generate_resume as _generate

    settings = get_settings()
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
        logger.exception("Resume generation failed for job_id=%s", body.job_id)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.post("/manual", response_model=dict)
def create_manual_resume_route(body: ResumeManualCreate):
    """Save a hand-built (user-pasted) markdown resume for a job."""
    from seeker_os.config import get_settings
    from seeker_os.resume.generator import create_manual_resume

    settings = get_settings()
    try:
        result = create_manual_resume(settings, job_id=body.job_id, resume_text=body.resume_text)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Manual resume save failed for job_id=%s", body.job_id)
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")


@router.post("/generate/stream")
def generate_resume_stream(body: ResumeGenerateRequest):
    """Generate a tailored resume with SSE progress streaming.

    Returns a text/event-stream with progress events as they occur,
    followed by a final 'done' event with the resume result.
    """
    from seeker_os.config import get_settings
    from seeker_os.resume.generator import generate_resume as _generate

    settings = get_settings()
    event_queue: queue.Queue = queue.Queue()

    def progress_cb(step: str, step_label: str, status: str, detail: str):
        event_queue.put({
            "step": step,
            "step_label": step_label,
            "status": status,
            "detail": detail,
        })

    def run_in_thread():
        try:
            logger.info("resume_stream job_id=%s: background thread started", body.job_id)
            result = _generate(
                settings=settings,
                job_id=body.job_id,
                task=body.task,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                progress_cb=progress_cb,
            )
            logger.info("resume_stream job_id=%s: background thread completed, putting done", body.job_id)
            event_queue.put(("done", result))
        except Exception as e:
            logger.exception("resume_stream job_id=%s: background thread failed", body.job_id)
            event_queue.put(("error", str(e)))

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    def _json_default(obj):
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()
        return str(obj)

    def event_stream():
        import time
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed > 300:
                logger.warning("resume_stream job_id=%s: SSE timeout after %.1fs", body.job_id, elapsed)
                yield f"event: error\ndata: {json.dumps({'error': 'Generation timeout (5min)'})}\n\n"
                break
            try:
                item = event_queue.get(timeout=5)
            except queue_module.Empty:
                # Send keepalive comment so the browser doesn't drop the connection
                yield ': keepalive\n\n'
                continue
            if isinstance(item, tuple):
                if item[0] == "done":
                    logger.info("resume_stream job_id=%s: SSE done event sent after %.1fs", body.job_id, time.monotonic() - start)
                    yield f"event: done\ndata: {json.dumps(item[1], default=_json_default)}\n\n"
                    break
                elif item[0] == "error":
                    logger.info("resume_stream job_id=%s: SSE error event sent after %.1fs", body.job_id, time.monotonic() - start)
                    yield f"event: error\ndata: {json.dumps({'error': item[1]}, default=_json_default)}\n\n"
                    break
            else:
                yield f"data: {json.dumps(item, default=_json_default)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{resume_id}/validate", response_model=dict)
def revalidate_resume(resume_id: int):
    """Re-run all validation gates on a stored resume.

    Runs accuracy, page-count, and ATS parse-survival gates against the
    stored resume text. Previous verdict is preserved in llm_evaluations.
    """
    from seeker_os.config import get_settings
    from seeker_os.validation import revalidate_all

    settings = get_settings()
    try:
        result = revalidate_all(resume_id, settings)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{resume_id}/exports", response_model=MessageResponse)
def clear_exports(resume_id: int):
    """Clear cached PDF and DOCX exports for a resume.

    Deletes the generated PDF/DOCX files from disk and nulls their paths in the DB.
    The markdown source is preserved. The next download request will regenerate
    the export from markdown on the fly.
    """
    db = get_connection()
    row = db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")

    cleared: list[str] = []
    for col in ("pdf_path", "docx_path"):
        p = row[col]
        if p:
            path = Path(p)
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
            cleared.append(col.replace("_path", "").upper())

    db.execute(
        "UPDATE resumes SET pdf_path=NULL, docx_path=NULL, updated_at=? WHERE id=?",
        (datetime.now(UTC).isoformat(), resume_id),
    )
    db.commit()
    db.close()

    if cleared:
        return MessageResponse(message=f"Cleared cached exports: {', '.join(cleared)}")
    return MessageResponse(message="No cached exports to clear")


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
    from seeker_os.config import get_settings
    settings = get_settings()
    nbh_terms = []
    try:
        cr = settings.channel_rules
        if cr and cr.resume and cr.resume.content_tiering:
            nbh_terms = cr.resume.content_tiering.non_breaking_hyphen_terms
    except Exception:
        pass
    md_path = Path(row["markdown_path"]) if row["markdown_path"] else None
    if md_path and md_path.exists():
        output = export_pdf(md_path, non_breaking_hyphen_terms=nbh_terms)
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
