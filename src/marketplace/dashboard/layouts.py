"""
layouts.py
==========
Page layout and reusable components. Presentation only — no data access and no
callback logic. Component IDs declared here are wired up in callbacks.py.
"""

from dash import dcc, html

from marketplace.dashboard import data_access


def _profile_options():
    df = data_access.list_profiles()
    if df.empty:
        return []
    return [{"label": r["label"], "value": r["profile_id"]} for _, r in df.iterrows()]


def _metal_options():
    return [{"label": m, "value": m} for m in data_access.list_metal_levels()]


def serve_layout():
    """Called on each page load so dropdowns reflect current data."""
    profiles = _profile_options()
    default_profile = profiles[0]["value"] if profiles else None

    return html.Div(
        style={"maxWidth": "1100px", "margin": "0 auto", "fontFamily": "sans-serif"},
        children=[
            html.H1("Marketplace Lens — Ohio Valley ACA Plans"),
            html.P("How does the cost of comparable coverage vary across counties?"),

            html.Div(
                style={"display": "flex", "gap": "1.5rem", "flexWrap": "wrap"},
                children=[
                    html.Div([
                        html.Label("Household profile"),
                        dcc.Dropdown(id="profile-dropdown", options=profiles,
                                     value=default_profile, clearable=False),
                    ], style={"minWidth": "320px"}),
                    html.Div([
                        html.Label("Metal levels"),
                        dcc.Dropdown(id="metal-dropdown", options=_metal_options(),
                                     multi=True, placeholder="All metal levels"),
                    ], style={"minWidth": "320px"}),
                ],
            ),

            html.H2("Median premium by county"),
            dcc.Graph(id="premium-map"),

            html.H2("Metal-level distribution"),
            dcc.Graph(id="metal-distribution"),

            html.H2("Plan comparison"),
            html.Label("County"),
            dcc.Dropdown(id="county-dropdown", placeholder="Pick a county"),
            html.Div(id="plan-table"),
        ],
    )
