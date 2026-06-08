"""
layouts.py
==========
Single-page layout built on dash-bootstrap-components (FLATLY theme).
Presentation only -- no data access logic and no callbacks. Component IDs
declared here are wired up in callbacks.py.

Structure, top to bottom:
  header band -> controls (profile builder + county + metals) -> 5 KPI cards
  -> two charts -> two more charts -> full-width plan comparison table.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from marketplace.dashboard import data_access


def _kpi_card(card_id, title):
    """A single metric card. Value is filled by a callback."""
    return dbc.Card(
        dbc.CardBody([
            html.Div(title, className="text-muted small text-uppercase fw-bold mb-1"),
            html.H3(id=card_id, className="mb-0 fw-bold"),
        ]),
        className="shadow-sm h-100",
    )


def _metal_options():
    return [{"label": m, "value": m} for m in data_access.list_metal_levels()]


def serve_layout():
    """Called on each page load so controls reflect current data."""
    bounds = data_access.profile_bounds()
    age_min, age_max = bounds["age_min"], bounds["age_max"]
    fpl_bands = bounds["fpl_bands"]
    default_age = age_min + (age_max - age_min) // 2

    header = html.Div(
        className="py-4 mb-4 border-bottom",
        children=dbc.Container([
            html.H2("Marketplace Lens", className="fw-bold mb-1"),
            html.P("How does the cost of comparable ACA coverage vary across the "
                   "Ohio Valley \u2014 Indiana, Ohio, Tennessee, and West Virginia?",
                   className="text-muted mb-0"),
        ]),
    )

    controls = dbc.Card(
        dbc.CardBody(dbc.Row([
            dbc.Col([
                html.Label("Your age", className="fw-bold small"),
                dcc.Slider(
                    id="age-slider", min=age_min, max=age_max, step=1,
                    value=default_age,
                    marks={a: str(a) for a in range(age_min, age_max + 1, 10)},
                    tooltip={"placement": "bottom", "always_visible": True},
                ),
            ], md=4),
            dbc.Col([
                html.Label("Income (% of federal poverty level)",
                           className="fw-bold small"),
                dcc.Dropdown(
                    id="fpl-dropdown",
                    options=[{"label": f"{b}% FPL", "value": b} for b in fpl_bands],
                    value=fpl_bands[len(fpl_bands) // 2] if fpl_bands else None,
                    clearable=False,
                ),
            ], md=3),
            dbc.Col([
                html.Label("County", className="fw-bold small"),
                dcc.Dropdown(id="county-dropdown", placeholder="All counties"),
            ], md=3),
            dbc.Col([
                html.Label("Metal levels", className="fw-bold small"),
                dcc.Dropdown(id="metal-dropdown", options=_metal_options(),
                             multi=True, placeholder="All"),
            ], md=2),
        ]), className="shadow-sm mb-2"),
    )

    snapped_note = html.P(id="snapped-profile",
                          className="text-muted small fst-italic mb-4")

    # Five cards across; on md they wrap to a tidy grid.
    kpis = dbc.Row([
        dbc.Col(_kpi_card("kpi-plans", "Plans available"),
                md=6, lg=True, className="mb-3"),
        dbc.Col(_kpi_card("kpi-median", "Median premium / mo"),
                md=6, lg=True, className="mb-3"),
        dbc.Col(_kpi_card("kpi-silver", "Cheapest Silver / mo"),
                md=6, lg=True, className="mb-3"),
        dbc.Col(_kpi_card("kpi-silver-credit", "Cheapest Silver / mo after credit"),
                md=6, lg=True, className="mb-3"),
        dbc.Col(_kpi_card("kpi-issuers", "Issuers"),
                md=6, lg=True, className="mb-3"),
    ])

    charts = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("Median premium by county", className="fw-bold"),
            dcc.Graph(id="premium-map", config={"displayModeBar": False}),
        ]), className="shadow-sm h-100"), md=6, className="mb-3"),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("Plans available by metal level", className="fw-bold"),
            dcc.Graph(id="metal-distribution", config={"displayModeBar": False}),
        ]), className="shadow-sm h-100"), md=6, className="mb-3"),
    ])

    charts2 = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("Full vs. after-credit premium", className="fw-bold"),
            html.Div("How much the premium tax credit buys down the sticker "
                     "price, by metal level.", className="text-muted small mb-2"),
            dcc.Graph(id="credit-comparison", config={"displayModeBar": False}),
        ]), className="shadow-sm h-100"), md=6, className="mb-3"),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("Comparison by issuer", className="fw-bold"),
            html.Div("Plans offered and median premium per insurer.",
                     className="text-muted small mb-2"),
            dcc.Graph(id="issuer-comparison", config={"displayModeBar": False}),
        ]), className="shadow-sm h-100"), md=6, className="mb-3"),
    ])

    table = dbc.Card(dbc.CardBody([
        html.H5("Plan comparison", className="fw-bold"),
        html.Div(id="plan-table"),
    ]), className="shadow-sm mb-4")

    return html.Div([
        header,
        dbc.Container([controls, snapped_note, kpis, charts, charts2, table],
                      fluid=False),
    ])