"""Build the source-only Minecraft gameplay kit from an explicit allowlist."""
# Copyright 2026 Wuyang Zhou and Tianyu Wei
# SPDX-License-Identifier: Apache-2.0

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = 'agents/skills/minecraft-gameplay/'
FILES = (
    'README.md', 'AGENTS.md', 'LICENSE', 'NOTICE', 'gitignore.template',
    SKILL + 'SKILL.md',
    SKILL + 'references/commands.md',
    SKILL + 'references/sequences.md',
    SKILL + 'runtime/minecraft_control.py',
    SKILL + 'runtime/minecraft_sequence.py',
    SKILL + 'runtime/test_minecraft_control.py',
    SKILL + 'runtime/test_minecraft_sequence.py',
    SKILL + 'runtime/requirements.txt',
    'scripts/package_gameplay.py',
    'scripts/setup_repository.py',
)


def build(root=ROOT, output=None):
    root = Path(root).resolve()
    output = Path(output or root / 'dist/minecraft-gameplay-portable.zip').resolve()
    if output.suffix.lower() != '.zip':
        raise ValueError('The output filename must end in .zip.')
    payload = {}
    for relative in FILES:
        source = root / relative
        # A source redirected outside the repository must not enter a release.
        source.resolve().relative_to(root)
        payload[relative] = source.read_bytes()
    manifest = {name: hashlib.sha256(content).hexdigest()
                for name, content in sorted(payload.items())}
    payload['MANIFEST.sha256.json'] = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(output.parent), suffix='.zip.tmp', delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(str(temporary), 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative, content in sorted(payload.items()):
                entry = zipfile.ZipInfo('minecraft-gameplay/' + relative, (1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(str(temporary)) as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError('ZIP integrity failure: ' + bad)
            for relative, expected in manifest.items():
                actual = hashlib.sha256(archive.read('minecraft-gameplay/' + relative)).hexdigest()
                if actual != expected:
                    raise RuntimeError('Payload hash mismatch: ' + relative)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(
        digest + '  ' + output.name + '\n', encoding='ascii')
    return {'archive': str(output), 'bytes': output.stat().st_size,
            'sha256': digest, 'payload_files': len(manifest),
            'zip_crc_and_payload_hashes': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Destination ZIP; defaults to dist/minecraft-gameplay-portable.zip.')
    args = parser.parse_args()
    print(json.dumps(build(output=args.output), indent=2))


if __name__ == '__main__':
    main()
