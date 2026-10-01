"""Native font faces: retain variable outlines and select axes in FreeType."""
import io
import json
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import ImageFont

WEIGHTS = {100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular',
           500: 'Medium', 600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold', 900: 'Black'}


def inspect_faces(data, filename, family_name=None):
    with TTFont(io.BytesIO(data)) as font:
        if font.flavor is not None:
            raise ValueError('Use TTF or OTF outlines')
        family = family_name or font['name'].getDebugName(16) or font['name'].getDebugName(1)
        style = font['name'].getDebugName(17) or font['name'].getDebugName(2)
        if not family or not style or ',' in family or len(f'{family},{style}') > 200:
            raise ValueError('Invalid font names')
        axes = list(font['fvar'].axes) if 'fvar' in font else []
        weight_axis = next((axis for axis in axes if axis.axisTag == 'wght'), None)
        weights = [w for w in WEIGHTS if weight_axis.minValue <= w <= weight_axis.maxValue] if weight_axis else [font['OS/2'].usWeightClass]
        intrinsic_italic = bool(font['OS/2'].fsSelection & 1) or 'italic' in style.lower() or 'oblique' in style.lower()
        variable_italic = any(axis.axisTag in ('ital', 'slnt') for axis in axes)
        faces = []
        for weight in weights:
            for italic in ([False, True] if variable_italic else [intrinsic_italic]):
                coordinates = []
                for axis in axes:
                    value = weight if axis.axisTag == 'wght' else (int(italic) if axis.axisTag == 'ital' else (-12 if italic else 0) if axis.axisTag == 'slnt' else axis.defaultValue)
                    coordinates.append(min(axis.maxValue, max(axis.minValue, value)))
                name = WEIGHTS.get(weight, style) if axes else style
                if axes and italic:
                    name = 'Italic' if name == 'Regular' else name + ' Italic'
                faces.append({'family': family, 'style': name, 'file': filename,
                              'axes': coordinates, 'weight': weight, 'italic': italic})
    # Native rendering validates the selected regular face without rewriting the font.
    regular = min(faces, key=lambda face: (face['italic'], abs(face['weight'] - 400)))
    image_font = ImageFont.truetype(io.BytesIO(data), 30)
    if regular['axes']:
        image_font.set_variation_by_axes(regular['axes'])
    image_font.getmask('Label 123')
    return faces


def register_faces(registry, directory, faces):
    fonts = {family: dict(styles) for family, styles in registry.fonts.items()}
    variations = dict(registry.variations)
    metadata = dict(registry.face_metadata)
    for face in faces:
        key = f"{face['family']},{face['style']}"
        fonts.setdefault(face['family'], {})[face['style']] = str(directory / face['file'])
        variations[key] = tuple(face['axes'])
        metadata[key] = {'weight': face['weight'], 'italic': face['italic']}
    aliases_file = directory / 'aliases.json'
    if aliases_file.exists():
        registry.aliases = {**registry.aliases, **json.loads(aliases_file.read_text())}
    registry.fonts, registry.variations, registry.face_metadata = fonts, variations, metadata


def load_installed(registry, directory):
    for folder in directory.iterdir() if directory.exists() else []:
        if not folder.is_dir() or folder.name.startswith('.'):
            continue
        manifest = folder / 'faces.json'
        if manifest.exists():
            register_faces(registry, folder, json.loads(manifest.read_text()))
        elif (folder / 'font.ttf').exists():
            path = folder / 'font.ttf'
            with TTFont(path) as font:
                family = font['name'].getDebugName(1)
                style = font['name'].getDebugName(2)
            if family and style:
                registry.fonts.setdefault(family, {})[style] = str(path)
