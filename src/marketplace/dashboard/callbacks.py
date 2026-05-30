"""
callbacks.py
============
Wires interactivity to the components declared in layouts.py. All data comes
through data_access; this module only shapes it into figures/tables.
"""

import plotly.express as px
from dash import Input, Output, dash_table, html

from marketplace.dashboard import data_access


def register_callbacks(app):
    @app.callback(
        Output("county-dropdown", "options"),
        Output("county-dropdown", "value"),
        Input("profile-dropdown", "value"),
    )
    def _populate_counties(profile_id):
        df = data_access.premium_by_county(profile_id)
        if df.empty:
            return [], None
        opts = [
            {"label": f"{r['county_name']}, {r['state']}", "value": r["county_fips"]}
            for _, r in df.sort_values("county_name").iterrows()
        ]
        return opts, opts[0]["value"] if opts else None

    @app.callback(
        Output("premium-map", "figure"),
        Input("profile-dropdown", "value"),
    )
    def _premium_map(profile_id):
        df = data_access.premium_by_county(profile_id)
        if df.empty:
            return px.scatter(title="No data loaded")
        # County-level choropleth needs FIPS + a GeoJSON; until that's wired in,
        # a ranked bar of median premium per county reads clearly.
        df = df.sort_values("median_premium")
        return px.bar(
            df, x="median_premium", y="county_name", orientation="h",
            labels={"median_premium": "Median monthly premium ($)",
                    "county_name": "County"},
            title="Median premium by county",
        )

    @app.callback(
        Output("metal-distribution", "figure"),
        Input("profile-dropdown", "value"),
    )
    def _metal_distribution(profile_id):
        df = data_access.metal_distribution(profile_id)
        if df.empty:
            return px.scatter(title="No data loaded")
        return px.bar(
            df, x="metal_level", y="plan_count",
            labels={"metal_level": "Metal level", "plan_count": "Plans available"},
            title="Plans available by metal level",
        )

    @app.callback(
        Output("plan-table", "children"),
        Input("profile-dropdown", "value"),
        Input("county-dropdown", "value"),
        Input("metal-dropdown", "value"),
    )
    def _plan_table(profile_id, county_fips, metal_levels):
        if not county_fips:
            return html.P("Select a county to compare plans.")
        df = data_access.plan_comparison(profile_id, county_fips, metal_levels)
        if df.empty:
            return html.P("No plans for this selection.")
        return dash_table.DataTable(
            columns=[{"name": c, "id": c} for c in df.columns],
            data=df.to_dict("records"),
            page_size=15,
            style_cell={"fontFamily": "sans-serif", "fontSize": "13px",
                        "textAlign": "left", "padding": "6px"},
            style_header={"fontWeight": "bold"},
            sort_action="native",
        )
