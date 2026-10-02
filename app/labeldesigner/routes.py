"""Compatibility redirect and authenticated image-printing webhook."""
import os
import hmac
import base64
from io import BytesIO
from flask import current_app, jsonify, redirect, url_for, request, make_response
from PIL import Image
from brother_ql.labels import ALL_LABELS, FormFactor
from . import bp
from .printer import PrinterQueue
from app.printing import print_image_queue
from .label import SimpleLabel, LabelContent, LabelOrientation, LabelType
from app.label_geometry import DEFAULT_DPI, printable_dimensions
from app.utils import convert_image_to_bw, convert_image_to_grayscale, convert_image_to_red_and_black, pdffile_to_image, imgfile_to_image

HIGH_RES_DPI = 600

@bp.errorhandler(ValueError)
def handle_value_error(e):
    return jsonify({"error": str(e)}), 400

@bp.route('/')
def index():
    return redirect(url_for('studio.index'))


def _convert_image(img: Image.Image, image_mode: str, bw_threshold: int = 70) -> Image.Image:
    if image_mode == 'grayscale':
        return convert_image_to_grayscale(img)
    elif image_mode == 'red_and_black':
        return convert_image_to_red_and_black(img)
    elif image_mode == 'colored':
        return img
    else:
        return convert_image_to_bw(img, bw_threshold)


def _scale_image_to_label(img: Image.Image, label_size: str, orientation: str,
                          high_res: bool = False) -> Image.Image:
    width, height = printable_dimensions(label_size, high_res)
    # Normalize: width = printable width, height = printable height
    if height > width:
        width, height = height, width
    if orientation == 'rotated':
        height, width = width, height

    kind = next((label.form_factor for label in ALL_LABELS if label.identifier == label_size), None)
    is_endless = kind == FormFactor.ENDLESS

    img_width, img_height = img.size
    if is_endless:
        # For endless labels, scale to fill the fixed dimension and let length vary
        if orientation == 'rotated':
            scale = height / img_height
        else:
            scale = width / img_width
    else:
        # For die-cut labels, fit within both dimensions
        scale = min(width / img_width, height / img_height)

    new_size = (max(1, int(img_width * scale)), max(1, int(img_height * scale)))
    return img.resize(new_size, Image.Resampling.LANCZOS)


@bp.route('/api/webhook/print', methods=['POST'])
def webhook_print():
    """
    Webhook endpoint for external services to print images directly.

    URL: POST /labeldesigner/api/webhook/print

    Accepts multiple images via multipart form-data or JSON with base64-encoded
    images. Each image is scaled to fit the target label dimensions and printed
    in batch with a cut after each label.

    Authentication:
        The webhook is disabled unless the WEBHOOK_PASSWORD environment variable
        (or config key) is set. Generate a secure password with:

            python3 -c "import secrets; print(secrets.token_urlsafe(32))"

        Then export it before starting the server:

            export WEBHOOK_PASSWORD="<generated-password>"

        Authenticate requests using one of:
        - Authorization header: ``Authorization: Bearer <password>``
        - Form/query parameter: ``password=<password>``
        - JSON body field: ``"password": "<password>"``

    Multipart form-data:
        - images: one or more image files (field name "images")
        - label_size: label size identifier (default: from config)
        - orientation: "standard" or "rotated" (default: from config)
        - image_mode: "grayscale", "bw", "red_and_black", "colored" (default: from config)
        - bw_threshold: black/white threshold 0-255 (default: from config)
        - high_res: 0 or 1 for 600 DPI (default: 0)
        - printer: printer device specifier (default: from config)
        - model: printer model (default: from config)

    JSON payload:
        {
            "images": [
                {"data": "<base64>", "mime": "image/png"},
                ...
            ],
            "label_size": "62",
            "orientation": "standard",
            "image_mode": "grayscale",
            "bw_threshold": 70,
            "high_res": 0,
            "printer": "...",
            "model": "..."
        }
    """
    # Webhook is disabled unless WEBHOOK_PASSWORD is configured
    webhook_password = current_app.config.get('WEBHOOK_PASSWORD', '')
    if not webhook_password:
        return make_response(jsonify({'success': False, 'message': 'Webhook is not enabled'}), 403)

    # Parse JSON body once (only when content type indicates JSON, not for multipart)
    jdata = request.get_json(silent=True) or {}

    # Authenticate: accept password via Authorization Bearer token, query param, or JSON field
    provided = (request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
                or request.values.get('password', '')
                or jdata.get('password', ''))
    if not provided or not hmac.compare_digest(provided, webhook_password):
        return make_response(jsonify({'success': False, 'message': 'Unauthorized'}), 401)

    try:
        # Merge parameters from query/form and JSON body (query/form takes precedence)
        def _param(key, default):
            return request.values.get(key) or jdata.get(key) or default

        label_size = _param('label_size', current_app.config['LABEL_DEFAULT_SIZE'])
        orientation = _param('orientation', current_app.config['LABEL_DEFAULT_ORIENTATION'])
        image_mode = _param('image_mode', current_app.config['IMAGE_DEFAULT_MODE'])
        bw_threshold = int(_param('bw_threshold', current_app.config['IMAGE_DEFAULT_BW_THRESHOLD']))
        high_res = int(_param('high_res', 0)) != 0
        device = _param('printer', current_app.config['PRINTER_PRINTER'])
        model = _param('model', current_app.config['PRINTER_MODEL'])

        # Validate label_size
        kind = next((label.form_factor for label in ALL_LABELS if label.identifier == label_size), None)
        if kind is None:
            return make_response(jsonify({'success': False, 'message': f'Unknown label_size: {label_size}'}), 400)

        # Determine label content type from image_mode
        if image_mode == 'grayscale':
            label_content = LabelContent.IMAGE_GRAYSCALE
        elif image_mode == 'red_and_black':
            label_content = LabelContent.IMAGE_RED_BLACK
        elif image_mode == 'colored':
            label_content = LabelContent.IMAGE_COLORED
        else:
            label_content = LabelContent.IMAGE_BW

        label_orientation = LabelOrientation.ROTATED if orientation == 'rotated' else LabelOrientation.STANDARD
        if kind == FormFactor.ENDLESS:
            label_type = LabelType.ENDLESS_LABEL
        elif kind == FormFactor.DIE_CUT:
            label_type = LabelType.DIE_CUT_LABEL
        else:
            label_type = LabelType.ROUND_DIE_CUT_LABEL

        width, height = printable_dimensions(label_size, high_res)
        if height > width:
            width, height = height, width
        if label_orientation == LabelOrientation.ROTATED:
            height, width = width, height

    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': 'Invalid request parameters'}), 400)

    # Collect images from request
    pil_images = []
    try:
        # Check for multipart file uploads first
        uploaded_files = request.files.getlist('images')
        if uploaded_files:
            for f in uploaded_files:
                if not f.filename:
                    continue
                _, ext = os.path.splitext(f.filename)
                ext = ext.lower()
                if ext == '.pdf':
                    img = pdffile_to_image(f, HIGH_RES_DPI if high_res else DEFAULT_DPI)
                else:
                    img = imgfile_to_image(f)
                pil_images.append(img)

        # Check for JSON payload with base64 images
        if not pil_images:
            if jdata and isinstance(jdata.get('images'), list):
                for entry in jdata['images']:
                    if isinstance(entry, str):
                        # Plain base64 string
                        img_bytes = base64.b64decode(entry)
                    elif isinstance(entry, dict) and 'data' in entry:
                        img_bytes = base64.b64decode(entry['data'])
                    else:
                        continue
                    img = Image.open(BytesIO(img_bytes))
                    pil_images.append(img)

    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': 'Failed to read images'}), 400)

    if not pil_images:
        return make_response(jsonify({'success': False, 'message': 'No images provided'}), 400)

    # Process and queue each image
    try:
        printer = PrinterQueue(model=model, device_specifier=device, label_size=label_size)
        for img in pil_images:
            img = _convert_image(img, image_mode, bw_threshold)
            img = _scale_image_to_label(img, label_size, orientation, high_res)
            label = SimpleLabel(
                width=width,
                height=height,
                label_content=label_content,
                label_orientation=label_orientation,
                label_type=label_type,
                image=img,
                image_fit=True,
                text=[],
            )
            printer.add_label_to_queue(label, cut=True, high_res=high_res)
        print_image_queue(printer)
        status = ""
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': str(e)}), 400)

    result = {
        'success': len(status) == 0,
        'count': len(pil_images)
    }
    if status:
        result['message'] = status
        return make_response(jsonify(result), 400)
    return jsonify(result)
