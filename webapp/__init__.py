from flask import Flask
import logging
import os
from bot.utils import to_shamsi
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect
import urllib.parse

load_dotenv()

def create_app():
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.INFO)

    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = os.getenv("APP_SECRET_KEY")
    CSRFProtect(app)

    from .auth_routes import auth_bp
    from .user_routes import user_bp
    from .admin_routes import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)


    app.jinja_env.filters['to_shamsi'] = to_shamsi
    app.jinja_env.filters['url_decode'] = lambda s: urllib.parse.unquote(s)



    logging.info("Flask app created and blueprints registered successfully.")
    return app