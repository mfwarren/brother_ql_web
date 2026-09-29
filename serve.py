"""Production entry point; static frontend and API share one listener."""
import os

from waitress import serve
from app import create_app

app = create_app()

if __name__ == '__main__':
    serve(app, host=os.environ.get('SERVER_HOST', app.config['SERVER_HOST']),
          port=int(os.environ.get('SERVER_PORT', app.config['SERVER_PORT'])),
          threads=4, max_request_body_size=8 * 1024 * 1024)
