"""Validate label drafts and shared API values at request boundaries."""
import barcode
import base64
import binascii
from flask import current_app
import app as app_module
from app.labeldesigner.media_catalog import supported_labels

MAX_IMAGE_BYTES = 5 * 1024 * 1024

class InputError(ValueError):
    pass

def string(value, name, max_length, *, allow_empty=False):
    if not isinstance(value, str) or len(value) > max_length or (not allow_empty and not value.strip()):
        raise InputError(f'Invalid {name}.')
    return value


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise InputError(f'{name} must be between {low} and {high}.')
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise InputError(f'Invalid {name}.')
    return value


def sizes():
    model = current_app.config['PRINTER_MODEL']
    return supported_labels(model)


def validate_draft(draft, *, allow_image_url=False):
    if not isinstance(draft, dict):
        raise InputError('Expected a label draft.')
    size = string(draft.get('sizeId'), 'label size', 32)
    available_sizes = {label.identifier for label in sizes()}
    if size not in available_sizes:
        raise InputError('Unknown label size.')
    orientation = draft.get('orientation')
    if orientation not in ('standard', 'rotated'):
        raise InputError('Invalid orientation.')
    font = app_module.FONTS.canonical_font(string(draft.get('font'), 'font', 200))
    draft = {**draft, 'font': font}
    if font not in {f"{family},{style}" for family, styles in app_module.FONTS.fonts.items() for style in styles}:
        raise InputError('Unknown font.')
    size_px = integer(draft.get('fontSize'), 'Font size', 8, 200)
    align = draft.get('align')
    if align not in ('left', 'center', 'right'):
        raise InputError('Invalid alignment.')
    if draft.get('verticalAlign', 'top') not in ('top', 'center', 'bottom'):
        raise InputError('Invalid vertical alignment.')
    color = draft.get('color')
    if color not in ('black', 'red'):
        raise InputError('Invalid color.')
    margin = integer(draft.get('margin'), 'Margin', 0, 100)
    if 'lineSpacing' in draft:
        integer(draft['lineSpacing'], 'Line spacing', 100, 300)
    if 'margins' in draft:
        margins = draft['margins']
        if not isinstance(margins, dict) or set(margins) != {'top', 'right', 'bottom', 'left'}:
            raise InputError('Provide all four margins.')
        for side, value in margins.items():
            integer(value, f'{side.title()} margin', 0, 100)
    high_res = boolean(draft.get('highRes'), 'highRes')
    if (color == 'red' or (isinstance(draft.get('content'), dict) and draft['content'].get('mode') == 'red')) and size != '62red':
        raise InputError('Red requires 62red media.')
    if high_res and size == '62red':
        raise InputError('High resolution is unavailable for red media.')
    content = draft.get('content')
    if not isinstance(content, dict):
        raise InputError('Choose text, QR, barcode, or image content.')
    kind = content.get('kind')
    image_bytes = None
    if kind == 'text':
        string(content.get('text'), 'text', 10000)
        if 'paragraphs' in content:
            from app.rich_text import validate_paragraphs
            try:
                validate_paragraphs(content['paragraphs'], content['text'])
            except ValueError as error:
                raise InputError(str(error))
    elif kind == 'qr':
        string(content.get('code'), 'QR code', 2000)
        string(content.get('caption'), 'caption', 10000, allow_empty=True)
    elif kind == 'barcode':
        value = string(content.get('code'), 'barcode value', 80)
        string(content.get('caption'), 'caption', 10000, allow_empty=True)
        format = content.get('format')
        if format not in ('code128', 'ean13', 'ean8', 'upca'):
            raise InputError('Unknown barcode type.')
        lengths = {'ean13': 12, 'ean8': 7, 'upca': 11}
        if format == 'code128':
            if not all(32 <= ord(char) <= 126 for char in value):
                raise InputError('Code 128 supports printable ASCII text and numbers.')
        elif format in lengths:
            length = lengths[format]
            if not value.isascii() or not value.isdigit() or len(value) not in (length, length + 1):
                raise InputError(f'{format.upper()} requires {length} digits, or {length + 1} including its check digit.')
            encoded = barcode.get_barcode_class(format)(value).get_fullcode()
            if len(value) == length + 1 and value != encoded:
                raise InputError('Incorrect barcode check digit.')
        else:
            raise InputError('Unknown barcode type.')
    elif kind == 'image':
        string(content.get('caption'), 'caption', 10000, allow_empty=True)
        if content.get('mode') not in ('grayscale', 'bw', 'red'):
            raise InputError('Invalid image mode.')
        boolean(content.get('fit'), 'image fit')
        if allow_image_url and content.get('imageUrl'):
            string(content['imageUrl'], 'image URL', 2000)
            return draft, None
        image = content.get('image')
        if not isinstance(image, dict):
            raise InputError('Choose an image.')
        name = string(image.get('name'), 'image name', 255)
        mime = image.get('mime')
        suffixes = {'image/png': '.png', 'image/jpeg': '.jpg', 'application/pdf': '.pdf'}
        if mime not in suffixes:
            raise InputError('Unsupported image type.')
        encoded = string(image.get('base64'), 'image data', 7_000_000)
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise InputError('Invalid image data.')
        if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
            raise InputError('Image must be no larger than 5 MiB.')
        if not name.lower().endswith(('.png',) if mime == 'image/png' else ('.jpg', '.jpeg') if mime == 'image/jpeg' else ('.pdf',)):
            raise InputError('Image filename must match its file type.')
        if mime == 'image/png' and not image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            raise InputError('Invalid PNG image.')
        if mime == 'image/jpeg' and not image_bytes.startswith(b'\xff\xd8'):
            raise InputError('Invalid JPEG image.')
        if mime == 'application/pdf' and not image_bytes.startswith(b'%PDF-'):
            raise InputError('Invalid PDF image.')
    else:
        raise InputError('Invalid content type.')
    return draft, image_bytes
