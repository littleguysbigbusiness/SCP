import io
import os
import re
import shutil

import pytesseract
from PIL import Image

MAX_PDF_PAGES = 5

if os.name == "nt" and shutil.which("tesseract") is None:
    _default_windows_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.isfile(_default_windows_path):
        pytesseract.pytesseract.tesseract_cmd = _default_windows_path

_LABEL_RE = re.compile(
    r"(?:(?P<designation>item\s*#)|"
    r"(?P<object_class>object\s*class)|"
    r"(?P<containment_procedures>special\s*containment\s*procedures)|"
    r"(?P<description>description))\s*:?",
    re.IGNORECASE,
)
_SCP_RE = re.compile(r"\bSCP-\d[\w-]*\b", re.IGNORECASE)


def _ocr_image(file_bytes):
    image = Image.open(io.BytesIO(file_bytes))
    return pytesseract.image_to_string(image)


def _ocr_pdf(file_bytes):
    from pdf2image import convert_from_bytes

    pages = convert_from_bytes(file_bytes)[:MAX_PDF_PAGES]
    return "\n".join(pytesseract.image_to_string(page) for page in pages)


def _clean(text):
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_fields(text):
    matches = list(_LABEL_RE.finditer(text))
    sections = {}
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[match.lastgroup] = _clean(text[start:end])

    designation = sections.get("designation", "").splitlines()[0].strip() if sections.get("designation") else ""
    if not designation:
        scp_match = _SCP_RE.search(text)
        designation = scp_match.group(0).upper() if scp_match else ""

    object_class = sections.get("object_class", "")
    object_class = object_class.splitlines()[0].strip() if object_class else ""

    return {
        "designation": designation,
        "object_class": object_class,
        "description": sections.get("description", ""),
        "containment_procedures": sections.get("containment_procedures", ""),
    }


def extract_archive_fields(file_bytes, mimetype):
    if mimetype == "application/pdf":
        text = _ocr_pdf(file_bytes)
    elif mimetype and mimetype.startswith("image/"):
        text = _ocr_image(file_bytes)
    else:
        raise ValueError("Unsupported file type for document reading: {}".format(mimetype or "unknown"))

    if not text.strip():
        raise RuntimeError("Could not read any text from this document.")

    return _extract_fields(text)
