"""Parse uploaded files (PDF, TXT, MD) into plain text with metadata."""

import re
from pathlib import Path


def parse_pdf(filepath):
    """Parse PDF file using pymupdf, preserving chapter/section structure."""
    import fitz  # pymupdf

    doc = fitz.open(filepath)
    sections = []
    current_chapter = ""
    current_section = ""
    current_text = []

    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                text = "".join(span["text"] for span in line["spans"]).strip()
                if not text:
                    continue

                # Detect headings by font size
                max_size = max(span["size"] for span in line["spans"])
                is_bold = any(span["flags"] & 2 ** 4 for span in line["spans"])

                if max_size >= 16 or (max_size >= 14 and is_bold):
                    # Save accumulated text
                    if current_text:
                        sections.append({
                            "chapter": current_chapter,
                            "section": current_section,
                            "text": "\n".join(current_text)
                        })
                        current_text = []
                    if max_size >= 16:
                        current_chapter = text
                        current_section = ""
                    else:
                        current_section = text
                else:
                    current_text.append(text)

    # Save last section
    if current_text:
        sections.append({
            "chapter": current_chapter,
            "section": current_section,
            "text": "\n".join(current_text)
        })

    doc.close()

    # If no sections detected, return all text as one section
    if not sections:
        doc2 = fitz.open(filepath)
        full_text = ""
        for page in doc2:
            full_text += page.get_text() + "\n"
        doc2.close()
        sections = [{"chapter": "", "section": "", "text": full_text.strip()}]

    return sections


def parse_text(filepath):
    """Parse a plain text or markdown file, detecting headings."""
    text = Path(filepath).read_text(encoding="utf-8")
    sections = []
    current_chapter = ""
    current_section = ""
    current_text = []

    for line in text.split("\n"):
        stripped = line.strip()

        # Markdown headings
        if stripped.startswith("# "):
            if current_text:
                sections.append({
                    "chapter": current_chapter,
                    "section": current_section,
                    "text": "\n".join(current_text)
                })
                current_text = []
            current_chapter = stripped.lstrip("# ").strip()
            current_section = ""
        elif stripped.startswith("## "):
            if current_text:
                sections.append({
                    "chapter": current_chapter,
                    "section": current_section,
                    "text": "\n".join(current_text)
                })
                current_text = []
            current_section = stripped.lstrip("# ").strip()
        elif re.match(r'^[A-Z][A-Z\s]{5,}$', stripped):
            # ALL CAPS line = likely chapter heading
            if current_text:
                sections.append({
                    "chapter": current_chapter,
                    "section": current_section,
                    "text": "\n".join(current_text)
                })
                current_text = []
            current_chapter = stripped.title()
            current_section = ""
        else:
            current_text.append(line)

    if current_text:
        sections.append({
            "chapter": current_chapter,
            "section": current_section,
            "text": "\n".join(current_text)
        })

    if not sections:
        sections = [{"chapter": "", "section": "", "text": text}]

    return sections


def parse_file(filepath):
    """Parse any supported file type."""
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    if ext == ".pdf":
        return parse_pdf(str(filepath))
    elif ext in (".txt", ".md", ".text", ".markdown"):
        return parse_text(str(filepath))
    else:
        raise ValueError(f"Unsupported file type: {ext}")
