"""
callbacks.py
============
Wires interactivity to the components declared in layouts.py. All data comes
through data_access; this module only shapes it into figures/tables.

Filter independence:
  The age slider + FPL dropdown snap to the nearest stored profile. Changing
  them refreshes the county dropdown's OPTIONS (premiums are profile-specific),
  but the user's current county SELECTION is preserved when that county still
  exists for the new profile -- so adjusting age no longer resets the county.
  Every chart reads age, FPL, county, and metal independently.
"""

import plotly.express as px
from dash import Input, Output, State, dash_table, html

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
        annotations=[dict(text=msg, showarrow=False,
                          font=dict(size=14, color="#7f8c8d"))],
        xaxis={"visible": False}, yaxis={"visible": False},
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


def register_callbacks(app):

    # --- resolve the user's age/FPL to a real stored profile_id ------------
    @app.callback(
        Output("snapped-profile", "children"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
    )
    def _snapped_note(age, fpl):
        _, row = data_access.nearest_profile_id(age, fpl)
        if not row:
            return "No profiles loaded."
        return ("Showing the closest available profile: "
                f"{data_access.profile_label(row)}")

    # --- county dropdown: refresh OPTIONS, PRESERVE current selection ------
    @app.callback(
        Output("county-dropdown", "options"),
        Output("county-dropdown", "value"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
        State("county-dropdown", "value"),
    )
    def _populate_counties(age, fpl, current):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        opts = data_access.county_options(profile_id)
        valid_values = {o["value"] for o in opts}
        # Keep the user's county if it still exists for this profile; otherwise
        # leave it cleared (None = "All counties") rather than forcing one.
        new_value = current if current in valid_values else None
        return opts, new_value

    # --- KPI cards ---------------------------------------------------------
    @app.callback(
        Output("kpi-plans", "children"),
        Output("kpi-median", "children"),
        Output("kpi-silver", "children"),
        Output("kpi-silver-credit", "children"),
        Output("kpi-issuers", "children"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"),
    )
    def _kpis(age, fpl, county_fips):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        k = data_access.kpi_summary(profile_id, county_fips)
        return (k["plans"], k["median"], k["cheapest_silver"],
                k["cheapest_silver_credit"], k["issuers"])

    # --- median premium by county ------------------------------------------
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
        # Pin category order so Plotly can't re-group or re-sort the bars.
        order = df["county_label"].tolist()
        fig = px.bar(
            df, x="median_premium", y="county_label", orientation="h",
            category_orders={"county_label": order},
            labels={"median_premium": "Median monthly premium ($)",
                    "county_label": ""},
        )
        fig.update_traces(marker_color=_BAR_COLOR)
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10),
                          plot_bgcolor="white", height=460)
        return fig

    # --- plans available by metal level (responds to county + metal) -------
    @app.callback(
        Output("metal-distribution", "figure"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"),
        Input("metal-dropdown", "value"),
    )
    def _metal_distribution(age, fpl, county_fips, metal_levels):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.metal_distribution(profile_id, county_fips, metal_levels)
        if df.empty:
            return _empty_fig()
        fig = px.bar(
            df, x="metal_level", y="plan_count", color="metal_level",
            color_discrete_map=_METAL_COLORS,
            labels={"metal_level": "", "plan_count": "Plans available"},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10),
                          plot_bgcolor="white", height=460, showlegend=False)
        return fig

    # --- full vs after-credit premium (responds to county + metal) ---------
    @app.callback(
        Output("credit-comparison", "figure"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"),
        Input("metal-dropdown", "value"),
    )
    def _credit_comparison(age, fpl, county_fips, metal_levels):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.premium_vs_credit(profile_id, county_fips, metal_levels)
        if df.empty:
            return _empty_fig()
        fig = px.bar(
            df, x="metal_level", y="amount", color="kind", barmode="group",
            color_discrete_map={"Full premium": "#2c3e50",
                                "After credit": "#18bc9c"},
            labels={"metal_level": "", "amount": "Median monthly ($)", "kind": ""},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white",
                          height=460, legend=dict(orientation="h", y=1.1))
        return fig

    # --- comparison by issuer (responds to county + metal) -----------------
    @app.callback(
        Output("issuer-comparison", "figure"),
        Input("age-slider", "value"),
        Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"),
        Input("metal-dropdown", "value"),
    )
    def _issuer_comparison(age, fpl, county_fips, metal_levels):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.issuer_comparison(profile_id, county_fips, metal_levels)
        if df.empty:
            return _empty_fig()
        df = df.sort_values("plan_count")
        fig = px.bar(
            df, x="plan_count", y="issuer_name", orientation="h",
            color="median_premium", color_continuous_scale="Tealgrn",
            labels={"plan_count": "Plans offered", "issuer_name": "",
                    "median_premium": "Median $/mo"},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white",
                          height=460)
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
            return html.P("Select a county to compare plans.",
                          className="text-muted")
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