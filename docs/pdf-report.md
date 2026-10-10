# PDF report

The PDF report is a human-readable version of the AIBOM. It is meant for a compliance or procurement file: you can print it, sign it, and keep it next to the model it describes. The machine-readable BOM is attached inside the same file.

## Getting the report

- **In the UI.** On the AIBOM datasheet, choose **Download PDF report**. The browser saves the file under its suggested name.
- **Through the API.** `GET /api/aibom/report.pdf?model=<id>` returns the PDF as an attachment. See [api.md](api.md#get-apiaibomreportpdf).

The report is generated from the same data as the JSON AIBOM and the completeness score. Nothing is stored on the server. Each request fetches the Hub data again, or uses the in-memory cache.

## What is in the report

| Part | Contents |
|---|---|
| **Cover** | The model name and id, the completeness score and rating with a ruler, a description of up to 420 characters (shortened with an ellipsis), the key facts, the serial number and generation time, and the list of sections. |
| **01 Identity** | The model id, publisher, commit, library, access mode, creation and last-modified dates, downloads, likes and the repository link. |
| **02 Licence** | The licence as declared (SPDX identifier or named licence), with its link where one is given. |
| **03 Architecture and data** | Task, architecture, model family, context length, parameter count, weight dtypes, base model, and the training and evaluation datasets. |
| **04 Evaluation results** | The `model-index` metrics, as published on the card. Long values are shown to four significant figures, and the embedded JSON keeps the full value. Up to 40 rows appear in the PDF. Any others are listed in the embedded JSON. |
| **05 Considerations** | Intended use, limitations and risks, ethical considerations, and intended users, as stated in the model card. |
| **06 Files and digests** | A table of repository files with the path, role, size and SHA-256 digest where the Hub publishes one. Up to 60 rows appear in the PDF. The rest are listed in the embedded JSON. |
| **07 Completeness checklist** | The twelve checks, their weights, and whether each is present. |
| **08 Verification** | How to check the report against the source repository and the embedded BOM. |

Each page's footer shows the generation date, the app version, the reminder "Verify before compliance use" and the page number. Section 08 prints the full disclaimer:

> This report summarises public metadata from Hugging Face at the time it was generated. It is not legal advice, a licence determination or a certification. Check licence terms, intended use and evaluation claims against the source repository before relying on them for compliance.

## The embedded BOM

The complete CycloneDX 1.6 JSON is attached to the PDF as `aibom.cdx.json`. PDF viewers show it in the attachments panel, and tools can read it directly. A short Python example:

```python
import json

from pypdf import PdfReader

reader = PdfReader("Qwen-Qwen2.5-7B-Instruct-aibom.pdf")
bom = json.loads(reader.attachments["aibom.cdx.json"][0])
print(bom["specVersion"], bom["metadata"]["component"]["name"])
```

`PdfReader.attachments` maps each attachment name to a list of byte strings.

## Fonts and text

- The report uses three families built from IBM Plex: **CloudySans** (regular, medium and semibold), **CloudySerif** (regular, medium and italic) and **CloudyMono** (regular and medium). They embed only the glyphs the report uses, so the file stays small.
- The families are renamed because the SIL Open Font License does not allow modified versions to use the reserved name "Plex". The PDF files are re-packaged TrueType subsets, which this project treats as modified versions, so they carry their own names. See [fonts-and-licences.md](fonts-and-licences.md).
- Characters that the bundled fonts do not contain are printed as `?`.
- Chinese text, Japanese kana and CJK punctuation use reportlab's built-in `STSong-Light` CID font. That font is not embedded in the file, so the viewer supplies the glyphs. Korean Hangul is not in that font and prints as `?`. CJK text displays correctly only in viewers that have a CJK font available.

## File name

The download name is built from the model id: `report_filename()` replaces each run of characters outside `A–Z a–z 0–9 . _ -` with a single `-`, trims stray separators, and appends `-aibom.pdf`. For example, `Qwen/Qwen2.5-7B-Instruct` becomes `Qwen-Qwen2.5-7B-Instruct-aibom.pdf`.

## Size and speed

A fully documented model (the test fixture Nimbus) renders to four pages in about 0.2 seconds, locally. Check your own deployment's timings in the Vercel logs.

## Checking a report

1. Compare the cover facts with the model page on Hugging Face. Check the commit, the licence and the date.
2. Read section 07. A missing item is a documentation gap, not a judgement about the model.
3. Use the embedded `aibom.cdx.json` for tooling. Validate it with the CycloneDX 1.6 schema if your process requires that.
4. Confirm any licence, intended-use or evaluation claim against the source repository, as the disclaimer says.

## Limitations

- The report describes public metadata. It does not check the model's behaviour, safety or training data.
- Long model cards are shortened in the PDF. The embedded JSON keeps more of the text, up to the limits in [aibom-mapping.md](aibom-mapping.md#the-model-component).
- The layout is designed for A4 paper.
