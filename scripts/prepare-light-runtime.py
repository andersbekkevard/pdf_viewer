#!/usr/bin/env python3
"""Prepare derived light HTML for lazy fonts and data-only viewer startup."""
from __future__ import annotations
import argparse
import base64
import hashlib
import html
import json
import math
import pathlib
import re
import tempfile

FRAME = re.compile(r'<div\b[^>]*\bid=(["\'])(pf[0-9a-f]+)\1[^>]*>', re.I)
CLASS = re.compile(r'\bclass=(["\'])(.*?)\1', re.S)
ATTRIBUTE = re.compile(r'([\w-]+)=(["\'])(.*?)\2', re.S)
FACE = re.compile(r'@font-face\s*\{[^}]*\}', re.S)
FONT_URL = re.compile(r'url\(\s*(["\']?)(data:[^,()\s"\']+;base64,[A-Za-z0-9+/=\s]+)\1\s*\)', re.S)
DIMENSION = re.compile(r'\.([\w-]+)\s*\{\s*(width|height)\s*:\s*([0-9.]+)px\s*;?\s*\}')
EXTENSIONS = {b'wOFF': 'woff', b'wOF2': 'woff2', b'OTTO': 'otf', b'\0\1\0\0': 'ttf', b'true': 'ttf'}

def set_attribute(tag: str, name: str, value: str) -> str:
    tag = re.sub(r'\s+' + re.escape(name) + r'=(["\']).*?\1', '', tag, flags=re.S)
    return tag[:-1] + f' {name}="{html.escape(value, quote=True)}">'

def geometry(text: str) -> tuple[str, int]:
    rules: dict[tuple[str, str], set[float]] = {}
    styles = re.findall(r'<style\b[^>]*>(.*?)</style>', text, re.S | re.I)
    for style in styles:
        style = re.sub(r'/\*.*?\*/', '', style, flags=re.S)
        for name, prop, value in DIMENSION.findall(style):
            rules.setdefault((name, prop), set()).add(float(value))
    def dimension(tag: str, prop: str) -> float:
        classes = CLASS.search(tag)
        if not classes:
            raise ValueError('missing classes')
        values = set()
        for name in classes.group(2).split():
            values.update(rules.get((name, prop), ()))
        if len(values) != 1:
            raise ValueError('ambiguous declared dimensions')
        value = values.pop()
        if not math.isfinite(value) or not 0 < value < 1_000_000:
            raise ValueError('invalid dimensions')
        if re.search(r'\bstyle=', tag):
            raise ValueError('inline geometry override')
        return value
    frames = list(FRAME.finditer(text))
    if not frames:
        return text, 0
    records = []
    numbers = set()
    try:
        for index, match in enumerate(frames):
            tag = match.group()
            attrs = {key: value for key, _, value in ATTRIBUTE.findall(tag)}
            number = int(match.group(2)[2:], 16)
            if number in numbers or int(attrs.get('data-page-no', ''), 16) != number:
                raise ValueError('invalid page numbering')
            numbers.add(number)
            end = frames[index + 1].start() if index + 1 < len(frames) else len(text)
            chunk = text[match.end():end]
            pc = next((m.group() for m in re.finditer(r'<div\b[^>]*>', chunk)
                       if (c := CLASS.search(m.group())) and 'pc' in c.group(2).split()), None)
            pi = next((m.group() for m in re.finditer(r'<div\b[^>]*>', chunk)
                       if (c := CLASS.search(m.group())) and 'pi' in c.group(2).split()), None)
            if not pc or not pi or 'data-page-url' in attrs:
                raise ValueError('incomplete page')
            data = {key: value for key, _, value in ATTRIBUTE.findall(pi)}
            matrix = json.loads(html.unescape(data['data-data']))['ctm']
            if (len(matrix) != 6 or any(type(x) not in (float, int) or not math.isfinite(x) for x in matrix)
                    or matrix[0] * matrix[3] - matrix[1] * matrix[2] == 0):
                raise ValueError('invalid transform')
            size = (dimension(tag, 'width'), dimension(tag, 'height'), dimension(pc, 'height'))
            records.append((match, ','.join(format(x, '.12g') for x in size)))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return text, 0
    pieces, last = [], 0
    for match, value in records:
        pieces.extend((text[last:match.start()], set_attribute(match.group(), 'data-pdf2html-page-size', value)))
        last = match.end()
    pieces.append(text[last:])
    text = ''.join(pieces)
    text = re.sub(r'<html\b[^>]*>', lambda m: set_attribute(m.group(), 'data-pdf2html-declared-page-geometry', 'v1'), text, count=1)
    return text, len(records)

def prepare(text: str, prefix: str) -> tuple[str, dict[str, bytes], int]:
    fonts: dict[str, bytes] = {}
    def face(match: re.Match[str]) -> str:
        def url(item: re.Match[str]) -> str:
            payload = item.group(2).split(',', 1)[1]
            data = base64.b64decode(re.sub(r'\s+', '', payload), validate=True)
            extension = EXTENSIONS.get(data[:4])
            if extension is None:
                return item.group()
            name = hashlib.sha256(data).hexdigest() + '.' + extension
            fonts[name] = data
            return 'url("' + prefix.rstrip('/') + '/' + name + '")'
        return FONT_URL.sub(url, match.group())
    text = FACE.sub(face, text)
    text, count = geometry(text)
    return text, fonts, count

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('light_html', type=pathlib.Path)
    parser.add_argument('--font-dir', type=pathlib.Path, required=True)
    parser.add_argument('--font-url-prefix', required=True)
    args = parser.parse_args()
    if not args.light_html.name.endswith('.light.html'):
        parser.error('operate on a derived .light.html file; preserve canonical HTML')
    source = args.light_html.read_text(encoding='utf-8')
    text, fonts, count = prepare(source, args.font_url_prefix)
    args.font_dir.mkdir(parents=True, exist_ok=True)
    for name, data in fonts.items():
        path = args.font_dir / name
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError('existing content-addressed font differs: ' + str(path))
        else:
            try:
                with path.open('xb') as file:
                    file.write(data)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=args.light_html.parent, delete=False) as file:
            temporary = pathlib.Path(file.name)
            file.write(text)
        temporary.replace(args.light_html)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    print(json.dumps({'pages_with_declared_geometry': count, 'external_fonts': len(fonts),
                      'font_bytes': sum(map(len, fonts.values())), 'html_bytes': len(text.encode())}))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
