"""Studio blueprint and common HTTP boundary handling."""
from flask import Blueprint, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from app.validation import InputError

bp = Blueprint('studio', __name__)
MAX_REQUEST_BYTES = 8 * 1024 * 1024


@bp.errorhandler(InputError)
def bad_input(error):
    return jsonify(message=str(error)), 400


@bp.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(message='Request is too large.'), 413


def body():
    request.max_content_length = MAX_REQUEST_BYTES
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise InputError('Expected a JSON object.')
    return data
