"""Render structured inline text with native FreeType faces into the print image."""
import math
import re

from PIL import Image, ImageDraw, ImageFont, ImageChops
from brother_ql.labels import ALL_LABELS, FormFactor

import app as app_module
from app.labeldesigner.label import SimpleLabel
from app.labeldesigner.enums import LabelContent, LabelOrientation, LabelType


def validate_paragraphs(paragraphs, plain_text):
    if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 100:
        raise ValueError('Use 1–100 text paragraphs.')
    count = 0
    texts = []
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict) or set(paragraph) != {'runs'}:
            raise ValueError('Invalid text paragraph.')
        runs = paragraph['runs']
        if not isinstance(runs, list):
            raise ValueError('Invalid text runs.')
        count += len(runs)
        if count > 500:
            raise ValueError('Too many formatting changes in this label.')
        line = ''
        for run in runs:
            if not isinstance(run, dict) or set(run) - {'text', 'size', 'bold', 'italic', 'font', 'underline'}:
                raise ValueError('Invalid formatted text.')
            if not isinstance(run.get('text'), str) or '\n' in run['text'] or '\r' in run['text']:
                raise ValueError('Use separate paragraphs for line breaks.')
            if 'font' in run:
                if not isinstance(run['font'], str):
                    raise ValueError('Choose an installed font.')
                try:
                    app_module.FONTS.get_path(run['font'])
                except (ValueError, LookupError):
                    raise ValueError('Choose an installed font.')
            if 'size' in run and (type(run['size']) is not int or not 8 <= run['size'] <= 200):
                raise ValueError('Text size must be between 8 and 200 px.')
            for mark in ('bold', 'italic', 'underline'):
                if mark in run and type(run[mark]) is not bool:
                    raise ValueError('Invalid text style.')
            line += run['text']
        texts.append(line)
    if '\n'.join(texts) != plain_text or len(plain_text) > 2000:
        raise ValueError('Formatted text must match the label text and be at most 2,000 characters.')


def text_image(draft, width, height):
    fonts = {}
    registry = app_module.FONTS
    def get_font(run):
        name = registry.styled_face(run.get('font', draft['font']), run.get('bold', False), run.get('italic', False))
        size = run.get('size', draft['fontSize'])
        key = (name, size)
        if key not in fonts:
            font = ImageFont.truetype(registry.get_path(name), size)
            axes = registry.get_variations(name)
            if axes:
                font.set_variation_by_axes(list(axes))
            fonts[key] = font
        return fonts[key]

    fallback = get_font({})
    lines = []
    line = []
    advance = 0
    max_width = width or 11000
    def finish():
        nonlocal line, advance
        while line and not line[-1][0].strip():
            line.pop()
        if line:
            line[-1] = (line[-1][0].rstrip(), line[-1][1], line[-1][2])
        lines.append(line)
        line, advance = [], 0
    for paragraph in draft['content']['paragraphs']:
        for run in paragraph['runs']:
            font = get_font(run)
            for token in re.findall(r'\s+|\S+', run['text']):
                token_width = font.getlength(token)
                if line and advance + token_width > max_width and not token.isspace():
                    finish()
                if token_width > max_width:
                    fragment = ''
                    for char in token:
                        if fragment and advance + font.getlength(fragment + char) > max_width:
                            line.append((fragment, font, run.get('underline', False))); finish(); fragment = ''
                        fragment += char
                    token = fragment
                    token_width = font.getlength(token)
                if token:
                    line.append((token, font, run.get('underline', False)))
                    advance += token_width
        finish()
    layouts = []
    for runs in lines:
        ascent = max((font.getmetrics()[0] for _, font, _ in runs), default=fallback.getmetrics()[0])
        descent = max((font.getmetrics()[1] for _, font, _ in runs), default=fallback.getmetrics()[1])
        x, left, right = 0, 0, 0
        for text, font, underline in runs:
            box = font.getbbox(text, anchor='ls')
            left = min(left, x + box[0]); right = max(right, x + box[2])
            x += font.getlength(text)
        ink_width = math.ceil(max(right, x) - left)
        if ink_width > max_width:
            raise ValueError('Text exceeds the label width. Reduce the selected text size or margins.')
        layouts.append((runs, ascent, descent, left, ink_width))
    actual_width = width or max(1, max(layout[4] for layout in layouts))
    spacing = draft.get('lineSpacing', 100) / 100
    advances = [math.ceil((ascent + descent) * spacing) for _, ascent, descent, _, _ in layouts]
    actual_height = sum(advances[:-1]) + layouts[-1][1] + layouts[-1][2]
    if actual_height > (height or 11000) or actual_width * actual_height > 16_000_000:
        raise ValueError('Text exceeds the label height. Reduce text size, text, or margins.')
    image = Image.new('RGB', (actual_width, max(1, actual_height)), 'white')
    draw = ImageDraw.Draw(image)
    y = 0
    for index, (runs, ascent, descent, left, ink_width) in enumerate(layouts):
        x = {'left': 0, 'center': (actual_width-ink_width)/2, 'right': actual_width-ink_width}[draft['align']] - left
        for text, font, underline in runs:
            draw.text((x, y+ascent), text, font=font, fill=draft['color'], anchor='ls')
            if underline and text:
                thickness = max(1, round(font.size / 16))
                baseline = min(y + ascent + max(1, round(font.size / 12)), y + ascent + descent - thickness)
                draw.rectangle((x, baseline, x + font.getlength(text), baseline + thickness - 1), fill=draft['color'])
            x += font.getlength(text)
        y += advances[index]
    return image


def render_label(draft):
    media = next(label for label in ALL_LABELS if label.identifier == draft['sizeId'])
    width, height = media.dots_printable
    if draft['highRes']:
        width, height = width*2, height*2
    if height > width:
        width, height = height, width
    rotated = draft['orientation'] == 'rotated'
    if rotated:
        width, height = height, width
    left, right, top, bottom = (draft.get('margins', {}).get(side, draft['margin']) for side in ('left', 'right', 'top', 'bottom'))
    if (width and width <= left+right) or (height and height <= top+bottom):
        raise ValueError('Margins leave no printable text area.')
    image = text_image(draft, width-left-right if width else 0, height-top-bottom if height else 0)
    if 'verticalAlign' in draft and media.form_factor in (FormFactor.DIE_CUT, FormFactor.ROUND_DIE_CUT):
        available = height - top - bottom
        bounds = ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox()
        if bounds:
            image = image.crop((0, bounds[1], image.width, bounds[3]))
        offset = {'top': 0, 'center': (available-image.height)//2, 'bottom': available-image.height}[draft['verticalAlign']]
        aligned = Image.new('RGB', (image.width, available), 'white')
        aligned.paste(image, (0, offset))
        image = aligned
    label_type = (LabelType.ENDLESS_LABEL if media.form_factor == FormFactor.ENDLESS else
                  LabelType.DIE_CUT_LABEL if media.form_factor == FormFactor.DIE_CUT else LabelType.ROUND_DIE_CUT_LABEL)
    return SimpleLabel(width=width, height=height, label_content=LabelContent.IMAGE_COLORED,
                       label_orientation=LabelOrientation.ROTATED if rotated else LabelOrientation.STANDARD,
                       label_type=label_type, label_margin=(left, right, top, bottom), text=[], image=image)
