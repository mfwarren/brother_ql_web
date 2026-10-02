"""Build raster labels from Studio's validated rendering parameters."""
import os
from flask import json, current_app
from PIL import Image
from werkzeug.datastructures import FileStorage
from brother_ql.labels import ALL_LABELS, FormFactor
import app as app_module
from .label import SimpleLabel, LabelContent, LabelOrientation, LabelType
from app.utils import convert_image_to_bw, convert_image_to_grayscale, convert_image_to_red_and_black, pdffile_to_image, imgfile_to_image

DEFAULT_DPI = 300

def build_label(d: dict, files: dict):
    label_size = d.get('label_size', "62")
    kind = next((label.form_factor for label in ALL_LABELS if label.identifier == label_size), None)
    if kind is None:
        raise LookupError("Unknown label_size")
    context = {
        'label_size': label_size,
        'print_type': d.get('print_type', 'text'),
        'label_orientation': d.get('orientation', 'standard'),
        'kind': kind,
        'margin_top': int(d.get('margin_top', 12)),
        'margin_bottom': int(d.get('margin_bottom', 12)),
        'margin_left': int(d.get('margin_left', 20)),
        'margin_right': int(d.get('margin_right', 20)),
        'border_thickness': int(d.get('border_thickness', 1)),
        'border_roundness': int(d.get('border_roundness', 0)),
        'border_distanceX': int(d.get('border_distance_x', 0)),
        'border_distanceY': int(d.get('border_distance_y', 0)),
        'border_color': d.get('border_color', 'black'),
        'text': json.loads(d.get('text', '[]')),
        'barcode_type': d.get('barcode_type', 'QR'),
        'qrcode_size': int(d.get('qrcode_size', 10)),
        'qrcode_correction': d.get('qrcode_correction', 'L'),
        'image_mode': d.get('image_mode', "grayscale"),
        'image_bw_threshold': int(d.get('image_bw_threshold', 70)),
        'image_fit': int(d.get('image_fit', 1)) > 0,
        'image_crop': int(d.get('image_crop', 0)) > 0,
        'image_scaling_factor': float(d.get('image_scaling_factor', 100.0)),
        'image_rotation': int(d.get('image_rotation', 0)),
        'print_color': d.get('print_color', 'black'),
        'timestamp': int(d.get('timestamp', 0)),
        'high_res': int(d.get('high_res', 0)) != 0,
        'code_text': d.get('code_text', '').strip(),
    }

    def get_uploaded_image(image: FileStorage) -> Image.Image:
        name, ext = os.path.splitext(image.filename)
        ext = ext.lower()

        # Try to open as PDF
        if ext == '.pdf':
            image = pdffile_to_image(image, DEFAULT_DPI)
            if context['image_mode'] == 'grayscale':
                return convert_image_to_grayscale(image)
            else:
                return convert_image_to_bw(image, context['image_bw_threshold'])

        # Try to read with PIL
        exts = Image.registered_extensions()
        supported_extensions = {ex for ex, f in exts.items() if f in Image.OPEN}
        current_app.logger.info(f"Supported image extensions: {supported_extensions}")
        if ext in supported_extensions:
            image = imgfile_to_image(image)
            if context['image_mode'] == 'grayscale':
                return convert_image_to_grayscale(image)
            elif context['image_mode'] == 'red_and_black':
                return convert_image_to_red_and_black(image)
            elif context['image_mode'] == 'colored':
                return image
            else:
                return convert_image_to_bw(image, context['image_bw_threshold'])

        raise ValueError("Unsupported file type")

    print_type = context['print_type']
    image_mode = context['image_mode']
    if print_type == 'text':
        label_content = LabelContent.TEXT_ONLY
    elif print_type == 'qrcode':
        label_content = LabelContent.QRCODE_ONLY
    elif print_type == 'qrcode_text':
        label_content = LabelContent.TEXT_QRCODE
    elif image_mode == 'grayscale':
        label_content = LabelContent.IMAGE_GRAYSCALE
    elif image_mode == 'red_and_black':
        label_content = LabelContent.IMAGE_RED_BLACK
    elif image_mode == 'colored':
        label_content = LabelContent.IMAGE_COLORED
    else:
        label_content = LabelContent.IMAGE_BW

    label_orientation = LabelOrientation.ROTATED if context['label_orientation'] == 'rotated' else LabelOrientation.STANDARD
    if context['kind'] == FormFactor.ENDLESS:
        label_type = LabelType.ENDLESS_LABEL
    elif context['kind'] == FormFactor.DIE_CUT:
        label_type = LabelType.DIE_CUT_LABEL
    else:
        label_type = LabelType.ROUND_DIE_CUT_LABEL

    width, height = _get_label_dimensions(context['label_size'], context['high_res'])
    if height > width:
        width, height = height, width
    if label_orientation == LabelOrientation.ROTATED:
        height, width = width, height

    # For each line in text, we determine and add the font path
    for line in context['text']:
        if 'size' not in line or not str(line['size']).isdigit():
            current_app.logger.error(line)
            raise ValueError("Font size is required")
        if int(line['size']) < 1:
            raise ValueError("Font size must be at least 1")
        line['path'] = app_module.FONTS.get_path(line.get('font', ''))
        line['variations'] = app_module.FONTS.get_variations(line.get('font', ''))
        if len(line.get('text', '')) > 10_000:
            raise ValueError("Text is too long")

    fore_color = (255, 0, 0) if context['print_color'] == 'red' else (0, 0, 0)
    border_color = (255, 0, 0) if context['border_color'] == 'red' else (0, 0, 0)

    uploaded = files.get('image', None)
    image = None
    if uploaded is not None:
        image = get_uploaded_image(uploaded)

    return SimpleLabel(
        width=width,
        height=height,
        label_content=label_content,
        label_orientation=label_orientation,
        label_type=label_type,
        label_margin=(
            int(context['margin_left']),
            int(context['margin_right']),
            int(context['margin_top']),
            int(context['margin_bottom'])
        ),
        fore_color=fore_color,
        text=context['text'],
        barcode_type=context['barcode_type'],
        qr_size=context['qrcode_size'],
        qr_correction=context['qrcode_correction'],
        image=image,
        image_fit=context['image_fit'],
        image_crop=context['image_crop'],
        image_scaling_factor=context['image_scaling_factor'],
        image_rotation=context['image_rotation'],
        border_thickness=context['border_thickness'],
        border_roundness=context['border_roundness'],
        border_distance=(context['border_distanceX'], context['border_distanceY']),
        border_color=border_color,
        timestamp=context['timestamp'],
        counter=0,
        code_text=context['code_text']
    )


def _get_label_dimensions(label_size: str, high_res: bool = False):
    dimensions = next((label.dots_printable for label in ALL_LABELS if label.identifier == label_size), None)
    if dimensions is None:
        raise LookupError("Unknown label_size")
    if high_res:
        return (2 * dimensions[0], 2 * dimensions[1])
    return dimensions


