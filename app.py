import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from routes.users import users_bp


load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)

    allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:4200")
    origins = [origin.strip() for origin in allowed_origins.split(",") if origin.strip()]

    CORS(
        app,
        resources={r"/api/*": {"origins": origins}},
        supports_credentials=True,
    )

    app.register_blueprint(users_bp)

    @app.get("/api/health")
    def health_check():
        return jsonify({"success": True, "message": "Nivela API funcionando"}), 200

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"success": False, "error": "Recurso no encontrado"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return jsonify({"success": False, "error": "Metodo no permitido"}), 405

    @app.errorhandler(Exception)
    def internal_error(_error):
        return jsonify({"success": False, "error": "Error interno del servidor"}), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
