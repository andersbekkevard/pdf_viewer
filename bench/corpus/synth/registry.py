"""Generator registry: @generator("name", variants=[...]) on a function tmp -> {variant: bytes|Path}."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Generator:
    name: str
    fn: Callable[[Path], dict]
    doc: str
    variants: list[str] = field(default_factory=list)
    system_fonts: bool = False


GENERATORS: dict[str, Generator] = {}


def generator(name: str, variants: list[str] | None = None, system_fonts: bool = False):
    def wrap(fn):
        doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
        GENERATORS[name] = Generator(name, fn, doc, variants or [], system_fonts)
        return fn
    return wrap
