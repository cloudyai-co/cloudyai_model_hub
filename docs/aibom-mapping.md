# AIBOM field mapping and completeness score

This page explains how the AIBOM is built: which Hugging Face field becomes which CycloneDX field, what each `hf:*` and `aibom:*` property means, and how the completeness score is calculated. The output follows the CycloneDX 1.6 specification. The tests check every generated BOM against the vendored CycloneDX 1.6 JSON schema.

## Document structure

| CycloneDX field | Value |
|---|---|
| `bomFormat`, `specVersion` | `CycloneDX` and `1.6`. |
| `serialNumber` | A new `urn:uuid:` on each build. |
| `version` | `1`. |
| `metadata.timestamp` | The build time, in UTC. |
| `metadata.tools.components` | One `application` named `cloudyai-aibom-generator`, with the app version. |
| `metadata.component` | The model, as a `machine-learning-model` component (see below). |
| `components` | One `file` component per repository file, up to 200. |
| `dependencies` | The model depends on each file component. Present only when the file tree lists at least one file. |

Sources: the Hub model endpoint (`/api/models/{id}`), the raw README and `config.json` files (`/{id}/raw/main/...`), and the recursive file tree (`/api/models/{id}/tree/main?recursive=true`).

## The model component

| Hugging Face source | CycloneDX location | Notes |
|---|---|---|
| `id` | `group` and `name` | `group` is the organisation, or `null` for a bare name. The component's `bom-ref` is `model:<id>`. |
| `sha` (commit) | `version` | First 12 characters of the commit SHA, or `main` when no commit is known. The full SHA is in `hf:commitSha`. |
| Card `description`, or the first paragraph of the README | `description` | Truncated to 1,000 characters. |
| `license`, card `license`, or `license:*` tags | `licenses` | An SPDX id when the value is a known SPDX identifier, such as `apache-2.0` or `mit` (case-sensitive in the schema). Otherwise a named licence. A licence URL is kept when the card gives a public one. |
| Author or organisation | `supplier` | The `author` field, or the organisation name when there is no author, with its huggingface.co URL. |
| Card `license_link` | `externalReferences` (type `license`) | Only links that start with `http://` or `https://` are kept. |
| Model page, tree and README | `externalReferences` (types `website`, `distribution`, `documentation`) | Links to huggingface.co. |
| `pipeline_tag` | `modelCard.modelParameters.task` | |
| `config.model_type` | `modelCard.modelParameters.architectureFamily` | |
| `config.architectures[0]` | `modelCard.modelParameters.modelArchitecture` | |
| Card `datasets` | `modelCard.modelParameters.datasets` | Each entry has `type: dataset` and `name`. Names of the form `org/name` also get `contents.url`. At most 25 entries. |
| Card `model-index` metrics | `modelCard.quantitativeAnalysis.performanceMetrics` | Each entry has `type` (the metric's type, or its name when no type is given), `value` and `slice` (the dataset name). |
| README intended-use sections | `modelCard.considerations.useCases` | Matched on headings such as "Intended uses", "Direct use" and "Out-of-scope use". |
| README limitation sections | `modelCard.considerations.technicalLimitations` | Matched on headings with "limitation", "bias", "risks", "known issues" or "caveats". |
| README ethics sections | `modelCard.considerations.ethicalConsiderations` | Matched on "ethical", "ethics", "responsible use", "misuse", "societal impact" or "safety considerations". |
| README user sections | `modelCard.considerations.users` | Matched on "intended users", "target users" or "who should use". |

Section text is cut to 800 characters per item and to 25 items per section. Markdown is reduced to plain text: front matter, HTML comments, images and code fences are removed, and links keep their label.

### Properties on the model component

Hugging Face values that have no standard CycloneDX field are stored as `properties`. Each property's value is a string. A missing value is left out.

| Property | Meaning |
|---|---|
| `hf:totalParameters` | Parameter count from the repository's safetensors metadata, or `unknown`. The estimate from `config.json` is used only in Model selection, never in the BOM. |
| `hf:weightDtypes` | Parameter counts by tensor dtype from the safetensors metadata, for example `BF16:7615616512`. |
| `hf:totalSizeBytes` | Sum of the sizes of the files in the tree. |
| `hf:fileCount` | Number of files in the tree, including any beyond the 200 listed as components. |
| `hf:contextLength` | `max_position_embeddings` from `config.json`. |
| `hf:baseModel` | Base model(s) named in the card, comma-separated. |
| `hf:accessMode` | `open`, `gated-auto`, `gated-manual` or `gated`, from the Hub's `gated` field. |
| `hf:private` | `true` or `false`. |
| `hf:downloads`, `hf:downloadsAllTime`, `hf:likes` | Counts at the time of the request. |
| `hf:libraryName` | The `library_name` from the Hub. |
| `hf:createdAt`, `hf:lastModified` | Timestamps from the Hub. |
| `hf:commitSha` | The full commit SHA. |
| `aibom:completenessScore` | The completeness score, 0 to 100. |
| `aibom:completenessLevel` | `strong`, `partial` or `sparse`. |

## File components

Each entry in the file tree that is a regular file becomes a `file` component. Directories are skipped. Components are sorted with weights first, then configuration, tokenizer, licence and documentation files, then the rest. Within each group, larger files come first. The list is capped at 200 components. `hf:fileCount` gives the real total.

| Field | Value |
|---|---|
| `name` | Path inside the repository, such as `model-00001-of-00004.safetensors`. |
| `bom-ref` | `file:<path>`. |
| `hashes` | `SHA-256` with the digest, only for files stored in Git LFS. The LFS object ID is the SHA-256 digest. |
| `aibom:fileRole` | `weights` (for example `.safetensors`, `.bin`, `.pt`, `.gguf`, `.onnx`), `configuration` (`config.json`, `generation_config.json` and similar), `tokenizer`, `license`, `documentation` (README and other `.md`, `.rst` and `.txt` files), `code` (`.py` and similar), or `other`. |
| `hf:sizeBytes` | Size in bytes. |
| `hf:storage` | `lfs` or `git`, depending on how the Hub stores the file. |
| `hf:gitObjectId` | The Git blob ID of the file. |
| `hf:xetHash` | The Xet content hash, when the Hub provides one. |

Files stored directly in Git have no SHA-256 digest in the Hub's tree listing, so the BOM does not invent one.

## Completeness score

The score measures how well the model is documented, not how good or safe it is. It is a weighted checklist of twelve items. The weights add up to 100, and the score is the sum of the weights of the items that are present.

| Check | Weight | Counts as present when |
|---|---|---|
| `license` | 10 | A licence is found in the Hub metadata, the card, or a `license:*` tag. |
| `description` | 8 | The card has a description, or the README has an introductory paragraph. |
| `pipeline_tag` | 6 | The Hub reports a task (`pipeline_tag`). |
| `architecture` | 10 | `config.json` names an architecture or a `model_type`. |
| `datasets` | 10 | The card lists at least one training dataset. |
| `intended_use` | 12 | The README has a section matching the intended-use patterns. |
| `limitations` | 12 | The README has a section on limitations, bias, risks, known issues or caveats. |
| `ethical_considerations` | 8 | The README has a section on ethics, responsible use, misuse, societal impact or safety considerations. |
| `eval_results` | 10 | The card's `model-index` lists at least one evaluation result. |
| `parameter_count` | 8 | The repository has safetensors metadata with a total parameter count. |
| `tags` | 4 | The Hub lists at least one tag. |
| `author` | 2 | The Hub identifies an author or organisation. |

**Levels.** `strong` for 80 and above, `partial` for 50 to 79, and `sparse` for below 50. The same bands are used in the UI, the PDF and the BOM properties.

**What the score cannot see.** The checks look for sections and fields, not for their quality. A model card with a heading called "Limitations" and one useless sentence gets full marks for that item. Read the report, not only the number.

**Why a documented model can score low.** The section checks match heading words. A model card that uses different headings, or that keeps its content in tables or images, can score lower than it deserves. The PDF's checklist shows which check failed, so you can see whether the content is missing or just under another heading.

## Validation

- The tests generate AIBOMs from the fixture models and validate them against the vendored CycloneDX 1.6 schemas (`bom-1.6.schema.json`, `spdx.schema.json` and `jsf-0.82.schema.json`).
- To validate an AIBOM yourself, use the CycloneDX 1.6 JSON schema with any JSON Schema validator, or the official CycloneDX CLI.
- Schema validity shows that the document is well formed. It does not show that the Hub data is correct or current.

## Known gaps

- Training datasets are listed by name. The BOM does not hash them or describe their contents.
- The BOM does not record how the model was trained, who reviewed it, or any known vulnerabilities.
- Benchmarks come from the card's `model-index` metadata. They are reported as published and have not been verified.
- Only the model's own repository is described. Quantised variants, adapters and other repositories are separate BOMs.
