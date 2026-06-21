# SYVERN Instruction Augmentation Design

## Purpose

This work adds instruction-side augmentation for the verified SYVERN SFT
dataset. The current final dataset has 270 records whose SysML `output` values
pass the pinned SYVERN validator fingerprint, but many instructions are
template-like and describe only construct names. Instruction augmentation keeps
the verified code unchanged and creates more natural bilingual instructions for
the same outputs.

The goal is to improve robustness to real user phrasing without adding new
SysML knowledge or changing any validated model text.

## Scope

Included:

- A small-sample trial generation workflow before full generation.
- An OpenAI-compatible teacher client using environment variables.
- A prompt that asks the teacher model to read SysML code and emit natural
  instructions aligned with the code.
- Bilingual output: two Chinese instructions and one English instruction per
  source record.
- Derived JSONL datasets that preserve the original train/validation split.
- Lightweight quality checks for generated instructions.
- Reports for sample trial and full generation.
- Tests for parsing, augmentation shape, split preservation, and checks.

Excluded:

- Changing `data/sft/train.jsonl` or `data/sft/val.jsonl` in place.
- Re-validating or editing SysML `output` text.
- Adding new SysML examples or new construct coverage.
- Training a model.
- Committing API keys, generated secrets, or private provider details beyond
  non-secret configuration names.
- Using instruction augmentation to move records between train and validation.

## Data Strategy

The original datasets remain canonical:

- `data/sft/train.jsonl`
- `data/sft/val.jsonl`

Augmented data is written under:

- `data/sft/instruction_aug/sample_aug.jsonl`
- `data/sft/instruction_aug/train_aug.jsonl`
- `data/sft/instruction_aug/val_aug.jsonl`
- `data/sft/instruction_aug/reports/sample_report.json`
- `data/sft/instruction_aug/reports/train_report.json`
- `data/sft/instruction_aug/reports/val_report.json`

Each augmented record copies these fields from its parent:

- `output`
- `input`
- `constructs`
- `source`
- `_syvern`

Each augmented record replaces only `instruction` and adds an augmentation
metadata object, tentatively named `_syvern_instruction_aug`, with:

- `augmented_from`: parent record id.
- `parent_output_sha256`: hash of the parent output.
- `teacher_model`: model id used by the teacher.
- `teacher_base_url_host`: host only, not a full secret-bearing URL.
- `prompt_version`.
- `language`: `zh` or `en`.
- `variant`: stable variant label such as `zh_task`, `zh_structural`, `en_task`.
- `batch_id`.
- `checks`: per-record quality check result.

The parent split is preserved. Records derived from train parents go only to
`train_aug.jsonl`; records derived from validation parents go only to
`val_aug.jsonl`.

## Teacher Configuration

The generator reads provider settings from environment variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `SYVERN_TEACHER_MODEL`

The initial model id is expected to be `gpt-5.5`, supplied through
`SYVERN_TEACHER_MODEL`. The script does not hard-code the API key, does not log
it, and does not write it to reports. If the provider uses an OpenAI-compatible
Chat Completions API, the implementation can call `/chat/completions` through a
minimal local client or the installed OpenAI SDK if available.

## Generation Workflow

The workflow has two phases.

Phase 1: sample trial.

- Select 20 source records from the combined train/validation set.
- Prefer broad construct coverage while keeping deterministic selection.
- Generate three instructions per selected record.
- Write `sample_aug.jsonl` and `sample_report.json`.
- Review the generated instructions manually before full generation.

Phase 2: full generation.

- Generate three instructions for every source train record.
- Generate three instructions for every source validation record.
- Write separate train and validation augmented files.
- Write reports with counts, failures, language distribution, duplicate counts,
  and quality check summaries.

If an individual parent fails generation or checking, the script records the
failure in the report and skips that generated variant. It must not create a
record with a low-confidence or malformed instruction.

## Prompt Contract

For each source record, the teacher receives:

- The SysML `output`.
- The construct list.
- The original instruction.
- The desired language and variant labels.

The teacher must return strict JSON with exactly three instruction candidates:

- `zh_task`: Chinese natural task request.
- `zh_structural`: Chinese engineering-style modeling request.
- `en_task`: English natural task request.

Instruction requirements:

- Ask for a SysML v2 model.
- Describe the modeling intent implied by the code.
- Mention important domain identifiers where helpful, such as package, part,
  port, state, action, requirement, or interface names.
- Avoid claiming behavior or domain semantics not present in the code.
- Avoid phrases that reveal the target code is being copied, such as "the code
  below", "same as this output", or "copy exactly".
- Keep each instruction concise enough for SFT use.

The prompt should tell the teacher to be conservative. If the code is too
abstract to infer a domain story, the teacher should produce a structural but
natural instruction rather than inventing domain semantics.

## Quality Checks

The local checker applies deterministic checks before writing augmented records:

- Instruction is a non-empty string.
- Instruction length is within configured bounds.
- Instruction does not contain forbidden leakage phrases.
- Instructions for the same parent are not exact duplicates after whitespace
  normalization.
- Generated records keep the exact parent output hash.
- Language is one of `zh` or `en`.
- Variant is one of the expected variant labels.
- Obvious CamelCase or identifier-like names mentioned in the instruction must
  appear in the parent output, except common terms such as `SysML`, `Model`,
  `System`, and `Vehicle` when they are generic in context.

The checker may also report soft warnings:

- Low identifier overlap with the parent output.
- Instruction mentions only generic construct vocabulary.
- Instruction is very close to the original template instruction.

Warnings are reported but do not automatically reject a record in the first
version. Rejection is reserved for malformed, duplicate, leaking, or obviously
unsupported instructions.

## Error Handling

- Missing `OPENAI_API_KEY`, `OPENAI_BASE_URL`, or `SYVERN_TEACHER_MODEL` causes
  a clear configuration error before any generation starts.
- Non-JSON teacher output is retried a small number of times, then recorded as a
  failure.
- Missing expected variants are recorded as failures for those variants.
- API errors are retried with bounded backoff.
- The script writes complete reports even when some records fail.
- The script never mutates source JSONL files.

## Testing

Required test coverage:

- Generated augmented records preserve parent `output` exactly.
- Train and validation augmentation preserve the parent split.
- The checker rejects empty instructions, forbidden leakage phrases, duplicate
  sibling instructions, invalid variants, invalid languages, and output hash
  mismatches.
- The checker reports soft warnings for weak identifier overlap.
- Teacher JSON parsing accepts valid strict JSON and rejects malformed payloads.
- Sample selection is deterministic and covers multiple constructs when
  possible.
- Reports include source counts, generated counts, accepted counts, rejected
  counts, language distribution, variant distribution, and failure reasons.

Network-backed teacher calls are kept out of ordinary unit tests. Tests should
use a fake teacher client.

## Delivery Criteria

The feature is accepted when:

- A sample trial command can generate up to 60 checked instruction variants from
  20 parent records.
- The sample report makes manual review easy.
- The full command can generate derived train and validation augmentation files
  without modifying the original 270 records.
- All generated records keep the exact parent output text and validator
  metadata.
- Unit tests for the augmentation utilities pass.
- Documentation explains how to set provider environment variables without
  storing secrets in the repository.

## Security Notes

The API key is sensitive. It must be passed through environment variables only.
It must not be committed, printed, added to reports, or stored in generated
JSONL metadata. Because a key was shared in chat during planning, rotating it
after this work is recommended.
