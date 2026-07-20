"""Deterministic parser for master_resume.md.

Splits the "Professional Experience" and "Early Career" sections into
addressable role/bullet units for Phase 1 deterministic bullet selection.
Pure text parsing — no LLM involved, no interpretation of meaning.

The parser is intentionally line-based and permissive: if a role or bullet
doesn't match the expected pattern, it's simply not captured as a unit
(the surrounding text is left untouched by any downstream filtering, since
filtering only ever removes lines that were captured as bullets).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SECTION_HEADING_RE = re.compile(r"^##\s+(.+)$")
_ROLE_HEADING_RE = re.compile(r"^###\s+(.+)$")
_COMPANY_LINE_RE = re.compile(
    r"^\*\*(?P<company>[^*]+)\*\*\s*(?:\((?P<detail>[^)]*)\))?\s*"
    r"·?\s*(?P<location>[^·]*)·\s*\*(?P<dates>[^*]+)\*"
)
_BULLET_RE = re.compile(r"^-\s+(?P<text>.+)$")
_SUBCONTEXT_RE = re.compile(r"^\*\((?P<context>[^)]+)\)\*\s*(?P<rest>.+)$")
_PIN_MARKER_RE = re.compile(r"\s*<!--\s*pin\s*-->\s*$", re.IGNORECASE)
_ITALIC_LINE_RE = re.compile(r"^\*(?P<text>.+)\*\s*$")

# Sections this parser addresses for role/bullet selection.
_ADDRESSABLE_SECTIONS = ("Professional Experience", "Early Career")
# Portfolio Projects is parsed into project blocks for Phase 1d.
_PORTFOLIO_SECTION = "Portfolio Projects"
# Core Competencies is parsed into category blocks for Phase 3.
_COMPETENCY_SECTION = "Core Competencies"
# Markdown table row: | **Label** | skills text |
_CATEGORY_ROW_RE = re.compile(
    r"^\|\s*\*\*(?P<label>[^*]+)\*\*\s*\|\s*(?P<skills>.+?)\s*\|$"
)
_CATEGORY_SEPARATOR_RE = re.compile(r"^\|[-\s|]+\|$")


@dataclass
class BulletUnit:
    """A single addressable bullet within a role or project, in its original order."""

    role_id: str
    bullet_index: int
    text: str
    sub_context: str | None = None
    line_no: int = -1
    pinned: bool = False
    project_id: str | None = None

    @property
    def key(self) -> str:
        owner = self.project_id or self.role_id
        return f"{owner}#{self.bullet_index}"


@dataclass
class RoleBlock:
    """A parsed role (job) block from Professional Experience or Early Career."""

    role_id: str
    title: str
    section: str  # "Professional Experience" | "Early Career"
    company_line: str = ""
    dates_raw: str = ""
    is_current: bool = False
    bullets: list[BulletUnit] = field(default_factory=list)
    heading_line: int = -1


@dataclass
class ProjectBlock:
    """A parsed project block from Portfolio Projects.

    Stack lines (italic tech-stack lines, URLs) are preserved verbatim
    as a multi-line block between the heading and the first bullet.
    """

    project_id: str
    title: str
    stack_lines: list[str] = field(default_factory=list)
    stack_line_nos: list[int] = field(default_factory=list)
    bullets: list[BulletUnit] = field(default_factory=list)
    heading_line: int = -1

    @property
    def has_bullets(self) -> bool:
        return len(self.bullets) > 0


@dataclass
class CategoryBlock:
    """A parsed competency category row from the Core Competencies table.

    The label is the bolded text in the Area column (e.g. "AI Infrastructure").
    The skills_text is the raw cell content (qualifiers preserved verbatim).
    The line_no is the 0-indexed line number for render filtering.
    """

    label: str
    skills_text: str
    line_no: int = -1


@dataclass
class ParsedMaster:
    lines: list[str]
    roles: list[RoleBlock]
    projects: list[ProjectBlock] = field(default_factory=list)
    categories: list[CategoryBlock] = field(default_factory=list)

    def roles_in_section(self, section: str) -> list[RoleBlock]:
        return [r for r in self.roles if r.section == section]

    def role_by_id(self, role_id: str) -> RoleBlock | None:
        for r in self.roles:
            if r.role_id == role_id:
                return r
        return None

    def project_by_id(self, project_id: str) -> ProjectBlock | None:
        for p in self.projects:
            if p.project_id == project_id:
                return p
        return None

    def category_by_label(self, label: str) -> CategoryBlock | None:
        for c in self.categories:
            if c.label == label:
                return c
        return None


def _slugify(text: str, seen: dict[str, int]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "role"
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def _parse_bullet(line: str, line_no: int, role_id: str, bullet_index: int, project_id: str | None = None) -> BulletUnit | None:
    """Parse a single bullet line into a BulletUnit, or None if not a bullet.

    Handles pin markers and sub-context annotations identically for both
    role bullets and project bullets.
    """
    bullet_match = _BULLET_RE.match(line)
    if not bullet_match:
        return None
    raw_text = bullet_match.group("text").strip()
    pinned = False
    pin_match = _PIN_MARKER_RE.search(raw_text)
    if pin_match:
        pinned = True
        raw_text = _PIN_MARKER_RE.sub("", raw_text).strip()
    sub_context = None
    sub_match = _SUBCONTEXT_RE.match(raw_text)
    if sub_match:
        sub_context = sub_match.group("context").strip()
        raw_text = sub_match.group("rest").strip()
    return BulletUnit(
        role_id=role_id,
        bullet_index=bullet_index,
        text=raw_text,
        sub_context=sub_context,
        line_no=line_no,
        pinned=pinned,
        project_id=project_id,
    )


def parse_master_resume(text: str) -> ParsedMaster:
    """Parse Professional Experience, Early Career, and Portfolio Projects
    into addressable role/bullet and project/bullet units. Deterministic,
    regex-based, no LLM.
    """
    lines = text.splitlines()
    roles: list[RoleBlock] = []
    projects: list[ProjectBlock] = []
    categories: list[CategoryBlock] = []
    current_section = ""
    current_role: RoleBlock | None = None
    current_project: ProjectBlock | None = None
    seen_slugs: dict[str, int] = {}
    seen_project_slugs: dict[str, int] = {}

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()

        section_match = _SECTION_HEADING_RE.match(line)
        if section_match:
            current_section = section_match.group(1).strip()
            current_role = None
            current_project = None
            continue

        # Parse role sections (Professional Experience, Early Career)
        if current_section in _ADDRESSABLE_SECTIONS:
            role_match = _ROLE_HEADING_RE.match(line)
            if role_match:
                title = role_match.group(1).strip()
                role_id = _slugify(title, seen_slugs)
                current_role = RoleBlock(
                    role_id=role_id,
                    title=title,
                    section=current_section,
                    heading_line=i,
                )
                roles.append(current_role)
                continue

            if current_role is None:
                continue

            if not current_role.company_line:
                company_match = _COMPANY_LINE_RE.match(line)
                if company_match:
                    current_role.company_line = line
                    dates_raw = company_match.group("dates").strip()
                    current_role.dates_raw = dates_raw
                    current_role.is_current = "present" in dates_raw.lower()
                    continue

            bullet = _parse_bullet(line, i, current_role.role_id, len(current_role.bullets))
            if bullet:
                current_role.bullets.append(bullet)
            continue

        # Parse Portfolio Projects section
        if current_section == _PORTFOLIO_SECTION:
            project_match = _ROLE_HEADING_RE.match(line)
            if project_match:
                title = project_match.group(1).strip()
                project_id = _slugify(title, seen_project_slugs)
                current_project = ProjectBlock(
                    project_id=project_id,
                    title=title,
                    heading_line=i,
                )
                projects.append(current_project)
                continue

            if current_project is None:
                continue

            # Stack lines: everything between heading and first bullet that
            # isn't a bullet or blank line. Preserved verbatim (may be
            # multi-line italics, URLs, etc.).
            bullet = _parse_bullet(line, i, "", len(current_project.bullets), project_id=current_project.project_id)
            if bullet:
                bullet.role_id = ""
                current_project.bullets.append(bullet)
            elif line:
                # Non-bullet, non-blank line within a project block —
                # collect as stack block content (verbatim).
                current_project.stack_lines.append(raw_line)
                current_project.stack_line_nos.append(i)
            continue

        # Parse Core Competencies section (markdown table)
        if current_section == _COMPETENCY_SECTION:
            cat_match = _CATEGORY_ROW_RE.match(line)
            if cat_match:
                label = cat_match.group("label").strip()
                skills = cat_match.group("skills").strip()
                categories.append(CategoryBlock(
                    label=label,
                    skills_text=skills,
                    line_no=i,
                ))
            continue

    return ParsedMaster(lines=lines, roles=roles, projects=projects, categories=categories)


def render_filtered_master(
    parsed: ParsedMaster,
    selections: dict[str, list[int]],
    dropped_project_ids: set[str] | None = None,
    dropped_category_line_nos: set[int] | None = None,
    kept_items: dict[str, list[str]] | None = None,
) -> str:
    """Rebuild the master resume text, keeping only the selected bullet
    indices (by original bullet_index, preserving original order) for roles
    and projects present in `selections`. Roles/projects not present in
    `selections` — and every non-bullet line — are left byte-for-byte
    untouched. Bullet text itself is never modified, only which bullet lines
    are kept vs. dropped.

    For projects in `dropped_project_ids`, the entire project block
    (heading, stack lines, and all bullets) is dropped from the output.
    Zero-bullet projects are also dropped from rendered output (they
    remain in the parse but produce no content lines — an empty
    placeholder section spends lines buying nothing).

    For competency categories, `dropped_category_line_nos` specifies the
    line numbers of category table rows to drop. The table header, separator,
    and any HTML comments are always preserved.

    For per-category item capping, `kept_items` maps category label -> list
    of kept item strings. When present, the skills text in the corresponding
    table row is rewritten to contain only the kept items, joined by ' · '.
    Items are dropped whole — surviving items are verbatim from the original.

    Non-bullet lines within role blocks (intro paragraphs, trailing notes)
    are always preserved — only bullet lines are subject to selection.
    """
    drop_lines: set[int] = set()

    # Role bullet drops
    for role in parsed.roles:
        if role.role_id not in selections:
            continue
        keep_indices = set(selections[role.role_id])
        for bullet in role.bullets:
            if bullet.bullet_index not in keep_indices:
                drop_lines.add(bullet.line_no)

    # Project bullet drops + entire project block drops
    dropped_project_ids = dropped_project_ids or set()
    for project in parsed.projects:
        if project.project_id in dropped_project_ids and project.has_bullets:
            # Drop the entire block: heading, stack lines, bullets
            drop_lines.add(project.heading_line)
            drop_lines.update(project.stack_line_nos)
            for bullet in project.bullets:
                drop_lines.add(bullet.line_no)
            continue
        if not project.has_bullets:
            # Zero-bullet project blocks are omitted from rendered output
            # to avoid empty placeholder sections consuming vertical space.
            drop_lines.add(project.heading_line)
            drop_lines.update(project.stack_line_nos)
            continue
        if project.project_id in selections:
            keep_indices = set(selections[project.project_id])
            for bullet in project.bullets:
                if bullet.bullet_index not in keep_indices:
                    drop_lines.add(bullet.line_no)

    # Competency category drops
    if dropped_category_line_nos:
        drop_lines.update(dropped_category_line_nos)

    # Build a lookup from line_no -> category label for item rewriting
    item_rewrite: dict[int, str] = {}
    if kept_items:
        for cat in parsed.categories:
            if cat.label in kept_items:
                # Rebuild the table row with only kept items
                kept = kept_items[cat.label]
                new_skills = " · ".join(kept)
                # Find the original line and reconstruct the table row
                original_line = parsed.lines[cat.line_no]
                # Match the table row pattern: | **Label** | skills |
                # Preserve the label portion exactly, replace skills
                import re as _re
                row_match = _re.match(r"^(\|\s*\*\*[^|]+\*\*\s*\|)\s*(.*)\s*\|\s*$", original_line)
                if row_match:
                    new_line = f"{row_match.group(1)} {new_skills} |"
                    item_rewrite[cat.line_no] = new_line

    out_lines = []
    for i, line in enumerate(parsed.lines):
        if i in drop_lines:
            continue
        # Strip pin markers from output — they must never appear in the
        # filtered master resume that goes to the LLM or traceability matching.
        stripped = _PIN_MARKER_RE.sub("", line)
        # Apply item-level rewriting for competency rows
        if i in item_rewrite:
            out_lines.append(item_rewrite[i])
        else:
            out_lines.append(stripped)
    return "\n".join(out_lines)
