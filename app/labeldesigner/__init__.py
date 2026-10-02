from flask import Blueprint

bp = Blueprint('labeldesigner', __name__)

from app.labeldesigner import routes