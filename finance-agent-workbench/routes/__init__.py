from routes.files import files_bp
from routes.models import models_bp
from routes.projects import projects_bp
from routes.workspace import workspace_bp
from routes.interactions import interactions_bp
from routes.agents import agents_bp
from routes.context import context_bp
from routes.project_data import project_data_bp
from routes.skills import skills_bp
from routes.apps import apps_bp, finmod_bp
from routes.dashboard import dashboard_bp


def register_blueprints(app):
    """Register API blueprints."""
    app.register_blueprint(files_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(workspace_bp)
    app.register_blueprint(interactions_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(context_bp)
    app.register_blueprint(project_data_bp)
    app.register_blueprint(skills_bp)
    app.register_blueprint(apps_bp)
    app.register_blueprint(finmod_bp)
    app.register_blueprint(dashboard_bp)
