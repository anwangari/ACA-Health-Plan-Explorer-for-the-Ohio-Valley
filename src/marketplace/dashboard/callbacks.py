"""
callbacks.py
============
Wires interactivity to the components declared in layouts.py. All data comes
through data_access; this module only shapes it into figures/tables.

The age slider + FPL dropdown are snapped to the nearest stored profile in
data_access.nearest_profile_id; every downstream query uses that real
profile_id, so the dashboard stays strictly read-only against the database.
"""

import plotly.express as px
from dash import Input, Output, dash_table, html

from marketplace.dashboard import data_access

# A restrained palette that sits well on the FLATLY theme.
_BAR_COLOR = "#2c3e50"
_METAL_COLORS = {
    "Bronze": "#cd7f32", "Expanded Bronze": "#b87333", "Silver": "#9aa0a6",
    "Gold": "#d4af37", "Platinum": "#7f8c8d", "Catastrophic": "#bdc3c7",
}


def _empty_fig(msg="No data for this selection"):
    fig = px.scatter()
    fig.update_layout(
        annotations=[dict(text=msg, showarrow=False, font=dict(size=14, color="#7f8c8d"))],
        xaxis={"visible": False}, yaxis={"visible": False},
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


def register_callbacks(app):

    # --- resolve the user's age/FPL to a real stored profile_id -------------
    @app.callback(
        Output("snapped-profile", "children"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
    )
    def _snapped_note(age, fpl):
        _, row = data_access.nearest_profile_id(age, fpl)
        if not row:
            return "No profiles loaded."
        return f"Showing the closest available profile: {data_access.profile_label(row)}"

    # --- county dropdown options follow the selected profile ----------------
    @app.callback(
        Output("county-dropdown", "options"),
        Output("county-dropdown", "value"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
    )
    def _populate_counties(age, fpl):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.premium_by_county(profile_id)
        if df.empty:
            return [], None
        opts = [
            {"label": f"{r['county_name']}, {r['state']}", "value": r["county_fips"]}
            for _, r in df.sort_values("county_name").iterrows()
        ]
        return opts, opts[0]["value"] if opts else None

    # --- KPI cards ----------------------------------------------------------
    @app.callback(
        Output("kpi-plans", "children"),
        Output("kpi-median", "children"),
        Output("kpi-silver", "children"),
        Output("kpi-issuers", "children"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"),
    )
    def _kpis(age, fpl, county_fips):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        k = data_access.kpi_summary(profile_id, county_fips)
        return k["plans"], k["median"], k["cheapest_silver"], k["issuers"]

    # --- premium by county --------------------------------------------------
    @app.callback(
        Output("premium-map", "figure"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
    )
    def _premium_map(age, fpl):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.premium_by_county(profile_id)
        if df.empty:
            return _empty_fig()
        df = df.sort_values("median_premium")
        fig = px.bar(
            df, x="median_premium", y="county_name", orientation="h",
            labels={"median_premium": "Median monthly premium ($)", "county_name": ""},
        )
        fig.update_traces(marker_color=_BAR_COLOR)
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10),
                          plot_bgcolor="white", height=420)
        return fig

    # --- metal-level distribution ------------------------------------------
    @app.callback(
        Output("metal-distribution", "figure"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
    )
    def _metal_distribution(age, fpl):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.metal_distribution(profile_id)
        if df.empty:
            return _empty_fig()
        fig = px.bar(
            df, x="metal_level", y="plan_count", color="metal_level",
            color_discrete_map=_METAL_COLORS,
            labels={"metal_level": "", "plan_count": "Plans available"},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10),
                          plot_bgcolor="white", height=420, showlegend=False)
        return fig

    # --- plan comparison table ---------------------------------------------
    @app.callback(
        Output("plan-table", "children"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"),
        Input("metal-dropdown", "value"),
    )
    def _plan_table(age, fpl, county_fips, metal_levels):
        if not county_fips:
            return html.P("Select a county to compare plans.", className="text-muted")
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.plan_comparison(profile_id, county_fips, metal_levels)
        if df.empty:
            return html.P("No plans for this selection.", className="text-muted")
        nice = {
            "plan_name": "Plan", "metal_level": "Metal", "plan_type": "Type",
            "monthly_premium": "Premium", "premium_after_credit": "After credit",
            "deductible_individual": "Deductible", "moop_individual": "Max OOP",
            "primary_care_copay": "PCP", "generic_drug_copay": "Generic Rx",
        }
        return dash_table.DataTable(
            columns=[{"name": nice.get(c, c), "id": c} for c in df.columns],
            data=df.to_dict("records"),
            page_size=15,
            style_cell={"fontFamily": "sans-serif", "fontSize": "13px",
                        "textAlign": "left", "padding": "8px"},
            style_header={"fontWeight": "bold", "backgroundColor": "#f8f9fa"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": "#fcfcfc"}
            ],
            sort_action="native",
        )