import base64
import json
import os

import anthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

_client = None


def get_client():
    global _client
    if _client is not None:
        return _client
    _client = anthropic.Anthropic()
    return _client


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "designation": {"type": "string"},
        "object_class": {"type": "string"},
        "description": {"type": "string"},
        "containment_procedures": {"type": "string"},
    },
    "required": ["designation", "object_class", "description", "containment_procedures"],
    "additionalProperties": False,
}

PROMPT = (
    "You are filing a scanned document into an SCP Foundation Archives record. "
    "Read the attached document and extract:\n"
    "- designation: the SCP number or item name/title if visible, otherwise your best short title for it\n"
    "- object_class: the object class (e.g. Safe, Euclid, Keter, Thaumiel) only if stated or clearly implied "
    "in the document, otherwise an empty string\n"
    "- description: a concise summary of what the document describes\n"
    "- containment_procedures: any containment, handling, or storage procedures described, otherwise an empty "
    "string\n"
    "Base every field only on what is actually visible in the document. Use an empty string for anything you "
    "cannot determine - never invent specifics."
)


def _content_block(file_bytes, mimetype):
    data = base64.standard_b64encode(file_bytes).decode("utf-8")
    if mimetype == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    if mimetype and mimetype.startswith("image/"):
        return {"type": "image", "source": {"type": "base64", "media_type": mimetype, "data": data}}
    raise ValueError("Unsupported file type for AI reading: {}".format(mimetype or "unknown"))


def extract_archive_fields(file_bytes, mimetype):
    content_block = _content_block(file_bytes, mimetype)

    response = get_client().messages.create(
        model=MODEL,
        max_tokens=2048,
        output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        messages=[{"role": "user", "content": [content_block, {"type": "text", "text": PROMPT}]}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to read this document.")

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
