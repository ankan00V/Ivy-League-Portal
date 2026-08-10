"""Strip document metadata from uploaded files before we store them.

A resume is not just its text. PDFs carry an `/Info` dictionary and an XMP packet;
DOCX files carry OOXML core properties. Between them they routinely record the
author's real name, their employer, the software licence holder, and every person
who has edited the file. A student uploading a CV last edited on their current
employer's machine hands us — and anyone who later reads that file — the employer's
name and often their own legal name, neither of which they typed into our form.

We were storing the uploaded bytes verbatim. This module rewrites the document so
only the content survives.

**Redaction fails open, deliberately.** If a PDF is malformed or a parser is
unavailable, we store the original rather than rejecting the upload: a student who
cannot upload a resume is locked out of the product's main personalisation signal,
which is a worse outcome than metadata we failed to strip. Every fallback logs at
warning level so the gap is visible rather than silent. This mirrors the fallback
posture used across the codebase for embeddings and skill extraction.

Legacy `.doc` is a binary OLE format with no parser in our dependency set. It is
passed through unchanged and that is recorded here rather than left to be discovered.
"""

from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)

#: Extensions we can actually rewrite. `.txt` carries no metadata by construction;
#: `.doc` has no parser available and is passed through.
REDACTABLE_EXTENSIONS = {".pdf", ".docx"}
PASSTHROUGH_EXTENSIONS = {".txt", ".doc"}


def strip_document_metadata(*, extension: str, content: bytes) -> tuple[bytes, bool]:
    """Return `(bytes_to_store, redacted)`.

    `redacted` is False whenever the original bytes are returned unchanged, whether
    because the format carries no metadata, because no parser was available, or
    because the document could not be rewritten.
    """
    suffix = (extension or "").lower().strip()

    if suffix == ".pdf":
        return _strip_pdf_metadata(content)
    if suffix == ".docx":
        return _strip_docx_metadata(content)

    if suffix not in PASSTHROUGH_EXTENSIONS:
        logger.warning("No metadata redaction path for extension %r; storing as uploaded.", suffix)
    return content, False


def _strip_pdf_metadata(content: bytes) -> tuple[bytes, bool]:
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception as exc:
        logger.warning("pypdf unavailable; storing PDF resume with its metadata intact: %s", exc)
        return content, False

    try:
        reader = PdfReader(BytesIO(content))
        if getattr(reader, "is_encrypted", False):
            # Rewriting an encrypted PDF would strip the owner's protection along
            # with the metadata. Leave it exactly as uploaded.
            logger.info("Encrypted PDF uploaded; skipping metadata redaction.")
            return content, False

        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        # A fresh PdfWriter starts with no /Info and no XMP packet. Setting them
        # explicitly to empty guards against pypdf carrying anything across and
        # documents the intent: we are not copying the source metadata.
        writer.add_metadata({})
        try:
            writer.xmp_metadata = None
        except Exception:
            # Older pypdf builds expose xmp_metadata read-only on the writer.
            # The packet is not copied by add_page, so this is belt-and-braces.
            pass

        buffer = BytesIO()
        writer.write(buffer)
        redacted = buffer.getvalue()
        if not redacted:
            logger.warning("PDF redaction produced empty output; storing the original.")
            return content, False
        return redacted, True
    except Exception as exc:
        logger.warning("PDF metadata redaction failed; storing the original: %s", exc)
        return content, False


#: OOXML core properties that can name a person or organisation. `created`,
#: `modified` and `revision` are timestamps/counters rather than identifiers, but
#: they are cleared too: an edit history is exactly the kind of metadata a student
#: does not expect to hand over with a CV.
_DOCX_TEXT_PROPERTIES = (
    "author",
    "last_modified_by",
    "comments",
    "category",
    "content_status",
    "identifier",
    "keywords",
    "language",
    "subject",
    "title",
    "version",
)


def _strip_docx_metadata(content: bytes) -> tuple[bytes, bool]:
    try:
        from docx import Document
    except Exception as exc:
        logger.warning("python-docx unavailable; storing DOCX resume with its metadata intact: %s", exc)
        return content, False

    try:
        document = Document(BytesIO(content))
        properties = document.core_properties

        for name in _DOCX_TEXT_PROPERTIES:
            try:
                setattr(properties, name, "")
            except Exception:
                logger.debug("Could not clear DOCX core property %r", name)

        for name in ("created", "modified", "last_printed"):
            try:
                setattr(properties, name, None)
            except Exception:
                logger.debug("Could not clear DOCX timestamp property %r", name)

        try:
            properties.revision = 1
        except Exception:
            logger.debug("Could not reset DOCX revision counter")

        buffer = BytesIO()
        document.save(buffer)
        redacted = buffer.getvalue()
        if not redacted:
            logger.warning("DOCX redaction produced empty output; storing the original.")
            return content, False
        return redacted, True
    except Exception as exc:
        logger.warning("DOCX metadata redaction failed; storing the original: %s", exc)
        return content, False
