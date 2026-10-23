# ADR-0022: Older Office formats, images and ZIP archives

Status: accepted (2026-10-23); built in steps, see Consequences

## Context
- Real project folders hold Office 97–2003 files (.doc, .xls, .ppt), screenshots and photos of whiteboards, and ZIP
  archives (e-mail exports, client deliveries). Today they are skipped as "no reader for this type".
- The laptop has no admin rights, but has Microsoft Office and Windows 10/11. Anything we add must install with pip
  through the proxy, or already be on the laptop.
- Extractors are a Strategy chosen by file name (`kb/extractors/for_path`), writing `text.md` with locator markers;
  pictures in `raw/<id>/figures/` are looked at by the model; citations are verified by locator only.

## Decision
1. **Same pattern, new readers.** Each format is one `Extractor`; nothing outside `kb/extractors/` learns about it.
   An extractor may return `meta["hint"]`, one sentence for the model about the format (an image, a deck), so
   `wiki.py` stops guessing formats from file names.
2. **.xls is read directly** with xlrd (BSD, pure Python): no Office needed. Both Excel readers only read cells; one
   builder, `sheets.SheetText`, writes the text, so .xls and .xlsx give the same text (numbers, dates, header rows).
3. **.doc and .ppt are converted by the user's own Office**, then read by the existing .docx/.pptx readers, so
   pictures, comments, speaker notes and hidden slides work the same (an Adapter, by composition). Office runs through
   COM from PowerShell: read-only, macros disabled, no alerts, killed after a timeout. **Without Office the extraction
   fails with a clear message** ("needs Microsoft Word on this laptop"); no low-quality fallback parser.
4. **Platform services behind ports** (`kb/core/ports.py`): `DocumentConverter` and `TextRecognizer`. Windows
   adapters in `kb/platform/windows/` (Office COM, Windows OCR through WinRT), a Null Object elsewhere or when the
   probe fails; one factory picks them and caches the probe. Extractors get them injected, tests use fakes.
5. **Images** (.png .jpg .jpeg .gif .webp .bmp .tif .tiff) are one-page sources: the picture goes to `figures/`
   (BMP/TIFF converted to PNG and very large pictures scaled down with Pillow), `text.md` holds `<!-- p. 1 -->` and
   the text recognised by the Windows OCR (or a note that none was found), so the model looks at the picture and
   cites `p. 1`.
6. **ZIP only in the app, unpacked in the browser** (`js/zip.js`, the browser's own `DecompressionStream`) before
   anything is sent, so its files appear in the folder preview with checkboxes like any folder (`archive.zip/...`).
   Limits against zip bombs (files, total size), encrypted and ZIP64 archives skipped with the reason, nested
   archives one level, paths cleaned. The server does not change; `kb add x.zip` is not supported.
7. **Feasibility first:** `setup/probe-formats.ps1` checks Word/PowerPoint COM, Windows OCR and the packages on the
   real laptop before the Windows adapters are relied on; `kb doctor formats` and About show what is available.

## Consequences
- Steps: probe (0.17.2) → .xls and the shared sheet builder → ports, adapters, diagnostics → images with OCR and
  `meta["hint"]` → .doc/.ppt through Office → ZIP in the browser.
- New dependencies: xlrd, Pillow (both permissive). Office and OCR are optional at run time.
- Office conversion cannot run in CI (no Office on the runners): it is covered by fakes and checked on the laptop.
