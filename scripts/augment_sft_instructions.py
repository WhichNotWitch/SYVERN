#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syvern.sft.instruction_aug import (
    AugmentationConfig,
    TeacherCandidate,
    parse_teacher_payload,
    run_instruction_augmentation,
)


SYSTEM_PROMPT = """You are a conservative SysML v2 instruction writer.

Your job is to write natural SFT instructions that ask for the given verified
SysML v2 model. The instruction should sound like a real user request, not a
catalog, benchmark summary, or code inventory.

Do not invent domain facts that are not present in the code.
Do not ask to copy, reproduce, or refer to "the code below".
For large models, summarize the main modeling intent instead of listing every
package, construct, action, attribute, port, or requirement.

Return strict JSON only."""


def config_from_env() -> AugmentationConfig:
    missing = [
        name
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "SYVERN_TEACHER_MODEL")
        if not os.environ.get(name)
    ]
    if missing:
        print(f"missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)
    return AugmentationConfig(
        teacher_model=os.environ["SYVERN_TEACHER_MODEL"],
        teacher_base_url=os.environ["OPENAI_BASE_URL"].rstrip("/"),
    )


class OpenAICompatibleTeacher:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float = 90.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def generate(self, record: Mapping[str, Any]) -> list[TeacherCandidate]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _user_prompt(record)},
            ],
            "temperature": 0.2,
            "max_tokens": 600,
        }
        response = self._post_json("/chat/completions", payload)
        content = _assistant_content(response)
        return parse_teacher_payload(content)

    def _post_json(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError("chat completion response must be a JSON object")
                    return data
            except (OSError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"teacher request failed: {last_error}")


def _assistant_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat completion response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("chat completion choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("chat completion choice missing message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("chat completion message content must be a string")
    return content


def _user_prompt(record: Mapping[str, Any]) -> str:
    record_id = record.get("id", "")
    constructs = record.get("constructs", [])
    original_instruction = record.get("instruction", "")
    output = record.get("output", "")
    return f"""Create exactly three SFT instructions for this verified SysML v2 output.

Return strict JSON in this shape:
{{
  "instructions": [
    {{"variant": "zh_task", "language": "zh", "instruction": "..."}},
    {{"variant": "zh_structural", "language": "zh", "instruction": "..."}},
    {{"variant": "en_task", "language": "en", "instruction": "..."}}
  ]
}}

Rules:
- zh_task: Chinese natural user request.
- zh_structural: Chinese engineering-style modeling request.
- en_task: English natural user request.
- Prefer a user-like request over a catalog of constructs.
- For large models, summarize the main modeling intent instead of listing every package, construct, action, attribute, port, or requirement.
- Do not enumerate more than 5 identifiers in one instruction.
- Chinese instructions must be <= 120 Chinese characters.
- English instructions must be <= 45 words.
- Mention important names from the code only when they are central to the request.
- Do not ask to copy the code or refer to "the code below".
- Do not invent semantics not supported by the code.
- Do not describe the file as a test suite, dataset sample, benchmark, or catalog unless that is clearly the modeling intent.

Record id: {record_id}
Constructs: {constructs}
Original instruction: {original_instruction}
SysML output:
```sysml
{output}
```
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate bilingual instruction-side SFT augmentation.")
    parser.add_argument("--mode", choices=("sample", "full"), required=True)
    parser.add_argument("--train", default="data/sft/train.jsonl")
    parser.add_argument("--val", default="data/sft/val.jsonl")
    parser.add_argument("--out-dir", default="data/sft/instruction_aug")
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--batch-id", default=None)
    args = parser.parse_args(argv)

    config = config_from_env()
    teacher = OpenAICompatibleTeacher(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=config.teacher_base_url,
        model=config.teacher_model,
    )
    result = run_instruction_augmentation(
        train_path=args.train,
        val_path=args.val,
        output_dir=args.out_dir,
        mode=args.mode,
        teacher=teacher,
        config=config,
        sample_limit=args.sample_limit,
        batch_id=args.batch_id,
    )
    print(json.dumps(result.report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
