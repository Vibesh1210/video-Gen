"""Voice catalog loaded from voices.yaml.

Each voice_id maps to either a reference WAV (clone mode) or a natural-
language description (design mode). The catalog is read once at startup.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml


@dataclass
class Voice:
    voice_id: str
    name: str
    language_code: str
    gender: str | None
    mode: Literal["clone", "design"]
    reference_wav: str | None = None
    prompt_text: str | None = None
    design_prompt: str | None = None

    def to_public(self) -> dict:
        return {
            "voice_id": self.voice_id,
            "name": self.name,
            "language_code": self.language_code,
            "gender": self.gender,
            "mode": self.mode,
            "sample_rate": 48000,
        }


class VoiceCatalog:
    def __init__(self, yaml_path: str | os.PathLike):
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"voices.yaml not found: {yaml_path}")

        raw = yaml.safe_load(yaml_path.read_text())
        if not isinstance(raw, list) or not raw:
            raise ValueError("voices.yaml must be a non-empty list of voice entries")

        self._base = yaml_path.parent
        self._voices: dict[str, Voice] = {}

        for entry in raw:
            v = self._parse(entry)
            self._voices[v.voice_id] = v

    def _parse(self, entry: dict) -> Voice:
        for required in ("voice_id", "name", "language_code", "mode"):
            if required not in entry:
                raise ValueError(f"voice entry missing '{required}': {entry}")

        mode = entry["mode"]
        if mode not in ("clone", "design"):
            raise ValueError(f"voice '{entry['voice_id']}' has invalid mode '{mode}'")

        ref = entry.get("reference_wav")
        if ref:
            ref = str((self._base / ref).resolve())
            if not Path(ref).exists():
                raise FileNotFoundError(f"reference_wav not found for voice "
                                        f"'{entry['voice_id']}': {ref}")

        if mode == "clone" and not ref:
            raise ValueError(f"voice '{entry['voice_id']}' is clone mode but "
                             f"has no reference_wav")
        if mode == "design" and not entry.get("design_prompt"):
            raise ValueError(f"voice '{entry['voice_id']}' is design mode but "
                             f"has no design_prompt")

        return Voice(
            voice_id=entry["voice_id"],
            name=entry["name"],
            language_code=entry["language_code"],
            gender=entry.get("gender"),
            mode=mode,
            reference_wav=ref,
            prompt_text=entry.get("prompt_text"),
            design_prompt=entry.get("design_prompt"),
        )

    def get(self, voice_id: str) -> Voice | None:
        return self._voices.get(voice_id)

    def list(self) -> list[Voice]:
        return list(self._voices.values())
