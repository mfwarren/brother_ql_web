"""Render validated Studio drafts directly, without form-field conversion."""
from io import BytesIO
from PIL import Image
import app as app_module
from app.label_geometry import DEFAULT_DPI, label_geometry, margins
from app.labeldesigner.label import SimpleLabel
from app.labeldesigner.enums import LabelContent
from app.utils import convert_image_to_bw, convert_image_to_grayscale, convert_image_to_red_and_black, pdf_bytes_to_image


def label_image(content, image_bytes):
    is_pdf = content['image']['mime'] == 'application/pdf'
    image = pdf_bytes_to_image(image_bytes, DEFAULT_DPI) if is_pdf else Image.open(BytesIO(image_bytes))
    if content['mode'] == 'grayscale':
        return convert_image_to_grayscale(image)
    if content['mode'] == 'red' and not is_pdf:
        return convert_image_to_red_and_black(image)
    return convert_image_to_bw(image, 70)


def render(draft, image_bytes):
    content = draft['content']
    kind = content['kind']
    if kind == 'text' and ('paragraphs' in content or 'verticalAlign' in draft or 'lineSpacing' in draft or 'margins' in draft):
        from app.rich_text import render_label
        if 'paragraphs' not in content:
            draft = {**draft, 'content': {**content, 'paragraphs': [{'runs': [{'text': line}]} for line in content['text'].split('\n')]}}
        return render_label(draft)
    geometry = label_geometry(draft)
    text = content['text'] if kind == 'text' else content.get('caption', '')
    lines = [{'text': line, 'font': draft['font'], 'size': str(draft['fontSize']),
              'align': draft['align'], 'color': draft['color'], 'line_spacing': str(draft.get('lineSpacing', 100)),
              'path': app_module.FONTS.get_path(draft['font']), 'variations': app_module.FONTS.get_variations(draft['font'])}
             for line in text.splitlines()]
    if kind == 'text':
        label_content = LabelContent.TEXT_ONLY
    elif kind in ('qr', 'barcode'):
        label_content = LabelContent.TEXT_QRCODE
    else:
        label_content = {'grayscale': LabelContent.IMAGE_GRAYSCALE, 'bw': LabelContent.IMAGE_BW,
                         'red': LabelContent.IMAGE_RED_BLACK}[content['mode']]
    label = SimpleLabel(width=geometry.width, height=geometry.height,
                        label_orientation=geometry.orientation, label_type=geometry.label_type,
                        label_content=label_content, label_margin=margins(draft),
                        fore_color=(255, 0, 0) if draft['color'] == 'red' else (0, 0, 0), text=lines,
                        barcode_type=content['format'] if kind == 'barcode' else 'QR',
                        code_text=content['code'].strip() if kind in ('qr', 'barcode') else '',
                        image=label_image(content, image_bytes) if kind == 'image' else None,
                        image_fit=content['fit'] if kind == 'image' else True)
    label.expand_templates = False
    return label
