"""
app.py
======
Dash application entry point. Assembles the layout and callbacks and starts the
dev server. Run via `python -m marketplace dashboard` or `python app.py`.
"""

from dash import Dash

from marketplace.logging_setup import get_logger
from marketplace.dashboard.layouts import serve_layout
from marketplace.dashboard.callbacks import register_callbacks
import dash_bootstrap_components as dbc

log = get_logger("dashboard")


def create_app():
    app = Dash(__name__, title="ACA Health Plan Explorer for the Ohio Valley",
           external_stylesheets=[dbc.themes.FLATLY])
    app.layout = serve_layout          # callable -> re-evaluated each page load
    register_callbacks(app)
    return app


# Module-level app so a WSGI server (gunicorn marketplace.dashboard.app:server)
# can find it in production.
app = create_app()
server = app.server


def main(debug=True, port=8050):
    log.info("Starting dashboard on http://127.0.0.1:%d", port)
    app.run(debug=debug, port=port)


if __name__ == "__main__":
    main()
