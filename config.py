"""
This are the default settings. (DONT CHANGE THIS FILE)
Adjust your settings in 'instance/application.py'
"""

import os
import logging

class Config(object):
    DEBUG = False
    LOG_LEVEL = logging.WARNING

    SERVER_PORT = 8013
    SERVER_HOST = '0.0.0.0'

    PRINTER_MODEL = 'QL-800'
    PRINTER_PRINTER = '?'

    LABEL_DEFAULT_ORIENTATION = 'standard'
    LABEL_DEFAULT_SIZE = '62'
    LABEL_DEFAULT_FONT_SIZE = 70
    LABEL_DEFAULT_FONT_FAMILY = 'DejaVu Serif'
    LABEL_DEFAULT_FONT_STYLE = 'Book'

    IMAGE_DEFAULT_MODE = 'grayscale'
    IMAGE_DEFAULT_BW_THRESHOLD = 70

    LABEL_DEFAULT_MARGIN_TOP = 24

    FONT_FOLDER = ''

    # Webhook print endpoint password. The webhook is disabled when empty.
    # Generate a secure password with:
    #   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
    WEBHOOK_PASSWORD = os.environ.get('WEBHOOK_PASSWORD', '')
