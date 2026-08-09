"""
layouts.py
==========
Single-page layout built on dash-bootstrap-components (FLATLY theme), designed
to fit a standard desktop viewport without scrolling: header -> controls ->
5 KPI cards -> a 2x2 grid of charts. The plan comparison table lives behind a
"Show plan details" toggle so it doesn't consume vertical space until needed.

Presentation only -- no data access logic and no callbacks. Component IDs
declared here are wired up in callbacks.py.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from marketplace.dashboard import data_access


def _kpi_card(card_id, title, desc=None):
    body = [
        html.Div(title, className="text-muted small text-uppercase fw-bold mb-1"),
        html.H4(id=card_id, className="mb-0 fw-bold"),
    ]
    if desc:
        body.append(html.Div(desc, className="text-muted mt-1",
                             style={"fontSize": "0.7rem", "lineHeight": "1.1"}))
    return dbc.Card(dbc.CardBody(body), className="shadow-sm h-100")


def _chart_card(title, graph_id, subtitle=None, height="230px"):
    body = [html.H6(title, className="fw-bold mb-1")]
    if subtitle:
        body.append(html.Div(subtitle, className="text-muted small mb-1"))
    body.append(dcc.Graph(id=graph_id, config={"displayModeBar": False},
                          style={"height": height}))
    return dbc.Card(dbc.CardBody(body), className="shadow-sm h-100")


def _metal_options():
    return [{"label": m, "value": m} for m in data_access.list_metal_levels()]


def serve_layout():
    bounds = data_access.profile_bounds()
    age_min, age_max = bounds["age_min"], bounds["age_max"]
    fpl_bands = bounds["fpl_bands"]
    default_age = age_min + (age_max - age_min) // 2

    header = html.Div(
        className="py-2 border-bottom mb-2",
        children=html.Div([
            html.H4("ACA Health Plan Explorer for the Ohio Valley", className="fw-bold mb-0"),
            html.Small("How does the cost of comparable ACA coverage vary across "
                       "the Ohio Valley \u2014 IN, OH, TN, WV?",
                       className="text-muted"),
        ], style={"maxWidth": "1200px", "margin": "0 auto",
                  "paddingLeft": "12px", "paddingRight": "12px"}),
    )

    controls = dbc.Card(dbc.CardBody(dbc.Row([
        dbc.Col([
            html.Label("Your age", className="fw-bold small"),
            dcc.Slider(id="age-slider", min=age_min, max=age_max, step=1,
                       value=default_age,
                       marks={a: str(a) for a in range(age_min, age_max + 1, 10)},
                       tooltip={"placement": "bottom", "always_visible": True}),
        ], md=3),
        dbc.Col([
            html.Label("Income (% FPL)", className="fw-bold small"),
            dcc.Dropdown(id="fpl-dropdown",
                         options=[{"label": f"{b}% FPL", "value": b} for b in fpl_bands],
                         value=fpl_bands[len(fpl_bands) // 2] if fpl_bands else None,
                         clearable=False),
        ], md=2),
        dbc.Col([
            html.Label("County", className="fw-bold small"),
            dcc.Dropdown(id="county-dropdown", placeholder="All counties"),
        ], md=4),
        dbc.Col([
            html.Label("Metal levels", className="fw-bold small"),
            dcc.Dropdown(id="metal-dropdown", options=_metal_options(),
                         multi=True, placeholder="All"),
        ], md=3),
    ], className="g-2")), className="shadow-sm mb-2")

    snapped_note = html.Small(id="snapped-profile",
                              className="text-muted fst-italic")

    kpis = dbc.Row([
        dbc.Col(_kpi_card("kpi-plans", "Plans available",
                          "Distinct plans you can choose from"), className="mb-2"),
        dbc.Col(_kpi_card("kpi-median", "Median premium / mo",
                          "Typical monthly price before subsidy"), className="mb-2"),
        dbc.Col(_kpi_card("kpi-silver", "Cheapest Silver / mo",
                          "Lowest Silver price before subsidy"), className="mb-2"),
        dbc.Col(_kpi_card("kpi-silver-credit", "Silver / mo after credit",
                          "Lowest Silver price after tax credit"), className="mb-2"),
        dbc.Col(_kpi_card("kpi-best-value", "Best value (est. annual)",
                          "Lowest total yearly cost; assumes you meet the deductible"),
                className="mb-2"),
    ], className="g-2 mb-1")

    grid = dbc.Row([
        dbc.Col(_chart_card("Median premium by county", "premium-map",
                            height="250px"),
                md=6, className="mb-2"),
        dbc.Col(_chart_card("Plans available by metal level", "metal-distribution"),
                md=6, className="mb-2"),
        dbc.Col(_chart_card("Premium vs. deductible (each dot is a plan)",
                            "value-scatter",
                            "Best-value plans sit toward the bottom-left. "
                            "Pick a county to populate."),
                md=6, className="mb-2"),
        dbc.Col(_chart_card("Estimated annual cost",
                            "annual-cost",
                            "Illustrative: premium \u00d7 12 + deductible "
                            "(assumes you meet the deductible). Pick a county."),
                md=6, className="mb-2"),
    ], className="g-2")

    plan_details = dbc.Card(dbc.CardBody([
        html.H6("Plan comparison", className="fw-bold"),
        html.Div(id="plan-table"),
    ]), className="shadow-sm mt-2 mb-4")

    return html.Div([
        header,
        html.Div(
            dbc.Container([controls, snapped_note, kpis, grid, plan_details],
                          fluid=True),
            style={"maxWidth": "1200px", "margin": "0 auto"},
        ),
    ])