"""Refresh the catalog from Google Fonts; font binaries download only on install."""
import json
import re
from pathlib import Path
from urllib.request import urlopen


def fetch(url):
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode().removeprefix(")]}'\n"))


def build(tree, metadata):
    if tree['truncated']:
        raise ValueError('Incomplete Google Fonts repository tree')
    names = {re.sub('[^a-z0-9]', '', f['family'].lower()): f['family']
             for f in metadata['familyMetadataList']}
    families = {}
    for entry in tree['tree']:
        parts = entry['path'].split('/')
        if len(parts) != 3 or parts[0] not in ('ofl', 'apache', 'ufl'):
            continue
        folder = '/'.join(parts[:2])
        family = families.setdefault(folder, {'id': folder, 'name': names.get(parts[1], parts[1]), 'files': []})
        if parts[2].lower().endswith('.ttf') or parts[2] in ('OFL.txt', 'LICENSE.txt', 'LICENCE.txt', 'UFL.txt'):
            family['files'].append(parts[2])
    families = [f for f in families.values() if any(p.endswith('.ttf') for p in f['files'])
                and any(p.endswith('.txt') for p in f['files'])]
    return {'revision': tree['sha'], 'families': sorted(families, key=lambda f: f['name'].lower())}


if __name__ == '__main__':
    catalog = build(fetch('https://api.github.com/repos/google/fonts/git/trees/main?recursive=1'),
                    fetch('https://fonts.google.com/metadata/fonts'))
    target = Path(__file__).resolve().parents[1] / 'app/data/google-fonts.json'
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')
    print(f"Catalogued {len(catalog['families'])} families")
