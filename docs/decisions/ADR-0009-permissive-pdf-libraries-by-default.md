---
id: ADR-0009
title: Permissive PDF libraries by default
status: proposed
date: 2026-10-18
note: to be confirmed by spike S3
---

# ADR-0009: Permissive PDF libraries by default

**Context.** PyMuPDF is AGPL; the tool may be distributed.

**Decision.** Default to pypdfium2 (text, images) and pdfplumber (tables); PyMuPDF is an optional adapter.

**Consequences.** Final choice after the benchmark on public PDFs.
