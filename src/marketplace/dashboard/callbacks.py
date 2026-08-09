"""
callbacks.py
============
Wires interactivity to the components declared in layouts.py. All data comes
through data_access; this module only shapes it into figures/tables.

Filter independence: the age slider + FPL dropdown snap to the nearest stored
profile. Changing them refreshes the county dropdown's OPTIONS but PRESERVES the
current county selection when it still exists. Every chart reads age, FPL,
county, metal, and (where relevant) usage independently.
"""

import plotly.express as px
from dash import Input, Output, State, dash_table, html

from marketplace.dashboard import data_access

_BAR_COLOR = "#2c3e50"
_METAL_COLORS = {
    "Bronze": "#cd7f32", "Expanded Bronze": "#b87333", "Silver": "#9aa0a6",
    "Gold": "#d4af37", "Platinum": "#7f8c8d", "Catastrophic": "#bdc3c7",
}
# Okabe-Ito colorblind-safe palette for the scatter, where telling plans apart
# matters more than literal metal colors. Maximally separated for all common
# types of color vision deficiency.
_METAL_COLORS_CB = {
    "Bronze": "#E69F00",          # orange
    "Expanded Bronze": "#D55E00", # vermilion
    "Silver": "#0072B2",          # blue
    "Gold": "#F0E442",            # yellow
    "Platinum": "#009E73",        # bluish green
    "Catastrophic": "#CC79A7",    # reddish purple
}
_COMPACT = dict(margin=dict(l=8, r=8, t=8, b=8), plot_bgcolor="white",
                height=230, font=dict(size=11))


def _empty_fig(msg="No data for this selection"):
    fig = px.scatter()
    fig.update_layout(
        annotations=[dict(text=msg, showarrow=False,
                          font=dict(size=13, color="#7f8c8d"))],
        xaxis={"visible": False}, yaxis={"visible": False}, **_COMPACT)
    return fig


def register_callbacks(app):

    @app.callback(
        Output("snapped-profile", "children"),
        Input("age-slider", "value"), Input("fpl-dropdown", "value"))
    def _snapped_note(age, fpl):
        _, row = data_access.nearest_profile_id(age, fpl)
        if not row:
            return "No profiles loaded."
        return f"Closest available profile: {data_access.profile_label(row)}"

    # county options refresh, selection preserved -------------------------
    @app.callback(
        Output("county-dropdown", "options"),
        Output("county-dropdown", "value"),
        Input("age-slider", "value"), Input("fpl-dropdown", "value"),
        State("county-dropdown", "value"))
    def _populate_counties(age, fpl, current):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        opts = data_access.county_options(profile_id)
        valid = {o["value"] for o in opts}
        return opts, (current if current in valid else None)

    # KPI cards (incl. best-value) ----------------------------------------
    @app.callback(
        Output("kpi-plans", "children"), Output("kpi-median", "children"),
        Output("kpi-silver", "children"), Output("kpi-silver-credit", "children"),
        Output("kpi-best-value", "children"),
        Input("age-slider", "value"), Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"), Input("metal-dropdown", "value"))
    def _kpis(age, fpl, county_fips, metals):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        k = data_access.kpi_summary(profile_id, county_fips)
        best = data_access.best_value_plan(profile_id, county_fips, "moderate", metals)
        if best:
            bv = f"${best['annual_cost']:,.0f}"
        else:
            bv = "Pick a county"
        return (k["plans"], k["median"], k["cheapest_silver"],
                k["cheapest_silver_credit"], bv)

    # median premium by county --------------------------------------------
    @app.callback(
        Output("premium-map", "figure"),
        Input("age-slider", "value"), Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"), Input("metal-dropdown", "value"))
    def _premium_map(age, fpl, county_fips, metals):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.premium_by_county(profile_id, metals)
        if df.empty:
            return _empty_fig()
        df = df.sort_values("median_premium")
        # Highlight the selected county; keep every bar so the comparison holds.
        if county_fips and county_fips in set(df["county_fips"]):
            colors = [("#e67e22" if f == county_fips else _BAR_COLOR)
                      for f in df["county_fips"]]
        else:
            colors = _BAR_COLOR
        fig = px.bar(df, x="median_premium", y="county_label", orientation="h",
                     category_orders={"county_label": df["county_label"].tolist()},
                     labels={"median_premium": "Median $/mo", "county_label": ""})
        fig.update_traces(marker_color=colors)
        # Fit all counties into a compact 250px box: small tick font + automargin
        # so every label shows without clipping, even when bars are thin.
        fit = dict(_COMPACT)
        fit["height"] = 250
        fit["margin"] = dict(l=8, r=8, t=8, b=8)
        fig.update_layout(yaxis=dict(automargin=True, tickfont=dict(size=8)),
                          **fit)
        return fig

    # plans by metal level (county + metal aware) -------------------------
    @app.callback(
        Output("metal-distribution", "figure"),
        Input("age-slider", "value"), Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"), Input("metal-dropdown", "value"))
    def _metal_distribution(age, fpl, county_fips, metals):
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.metal_distribution(profile_id, county_fips, metals)
        if df.empty:
            return _empty_fig()
        fig = px.bar(df, x="metal_level", y="plan_count", color="metal_level",
                     color_discrete_map=_METAL_COLORS,
                     labels={"metal_level": "", "plan_count": "Plans"})
        # Cap bar width so a 2-3 category selection doesn't stretch into huge
        # bars on a wide chart; stays dynamic since the plot still resizes.
        fig.update_traces(width=0.5)
        # Center the bars within the plot when there are only a few categories.
        fig.update_xaxes(range=[-0.5, max(len(df) - 0.5, 1.5)])
        fig.update_layout(showlegend=False, bargap=0.4, **_COMPACT)
        return fig

    # premium vs deductible scatter ---------------------------------------
    @app.callback(
        Output("value-scatter", "figure"),
        Input("age-slider", "value"), Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"), Input("metal-dropdown", "value"))
    def _value_scatter(age, fpl, county_fips, metals):
        if not county_fips:
            return _empty_fig("Pick a county to compare plans")
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.plan_value_scatter(profile_id, county_fips, metals)
        if df.empty:
            return _empty_fig()
        fig = px.scatter(
            df, x="premium_after_credit", y="deductible_individual",
            color="metal_level", color_discrete_map=_METAL_COLORS_CB,
            symbol="metal_level",
            hover_name="plan_name",
            labels={"premium_after_credit": "Premium / mo (after credit)",
                    "deductible_individual": "Deductible ($)", "metal_level": ""})
        fig.update_traces(marker=dict(size=11, opacity=0.85,
                                      line=dict(width=1, color="#333")))
        fig.update_layout(legend=dict(orientation="h", y=1.15,
                                      font=dict(size=9)), **_COMPACT)
        return fig

    # estimated annual cost ------------------------------------------------
    @app.callback(
        Output("annual-cost", "figure"),
        Input("age-slider", "value"), Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"), Input("metal-dropdown", "value"))
    def _annual_cost(age, fpl, county_fips, metals):
        if not county_fips:
            return _empty_fig("Pick a county to estimate cost")
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.annual_cost_estimate(profile_id, county_fips, "moderate", metals)
        if df.empty:
            return _empty_fig()
        df = df.head(12).sort_values("annual_cost", ascending=False)
        # Truncate long plan names so the bars get real width; keep the full
        # name for hover. Disambiguate any collisions the truncation creates.
        def _short(name, n=30):
            return name if len(name) <= n else name[:n - 1].rstrip() + "\u2026"
        df = df.copy()
        df["plan_label"] = df["plan_name"].map(_short)
        if df["plan_label"].duplicated().any():
            df["plan_label"] = [f"{lbl}  ({i + 1})" for i, lbl
                                in enumerate(df["plan_label"])]
        fig = px.bar(df, x="annual_cost", y="plan_label", orientation="h",
                     color="metal_level", color_discrete_map=_METAL_COLORS,
                     category_orders={"plan_label": df["plan_label"].tolist()},
                     custom_data=["plan_name"],
                     labels={"annual_cost": "Est. annual cost ($)", "plan_label": ""})
        fig.update_traces(
            hovertemplate="%{customdata[0]}<br>Est. annual: $%{x:,.0f}<extra></extra>")
        fig.update_xaxes(tickangle=0)
        fig.update_layout(showlegend=False,
                          yaxis=dict(automargin=True, tickfont=dict(size=10)),
                          **_COMPACT)
        return fig

    # plan comparison table ------------------------------------------------
    @app.callback(
        Output("plan-table", "children"),
        Input("age-slider", "value"), Input("fpl-dropdown", "value"),
        Input("county-dropdown", "value"), Input("metal-dropdown", "value"))
    def _plan_table(age, fpl, county_fips, metals):
        if not county_fips:
            return html.P("Select a county to compare plans.", className="text-muted")
        profile_id, _ = data_access.nearest_profile_id(age, fpl)
        df = data_access.plan_comparison(profile_id, county_fips, metals)
        if df.empty:
            return html.P("No plans for this selection.", className="text-muted")
        nice = {"plan_name": "Plan", "metal_level": "Metal", "plan_type": "Type",
                "monthly_premium": "Premium", "premium_after_credit": "After credit",
                "deductible_individual": "Deductible", "moop_individual": "Max OOP",
                "primary_care_copay": "PCP", "generic_drug_copay": "Generic Rx"}
        return dash_table.DataTable(
            columns=[{"name": nice.get(c, c), "id": c} for c in df.columns],
            data=df.to_dict("records"), page_size=15,
            # Keep the table inside its card: fit to container, scroll
            # horizontally within the table if columns need more room.
            style_table={"overflowX": "auto", "width": "100%", "minWidth": "100%"},
            style_cell={"fontFamily": "sans-serif", "fontSize": "13px",
                        "textAlign": "left", "padding": "8px",
                        "minWidth": "70px", "maxWidth": "220px",
                        "whiteSpace": "normal", "height": "auto",
                        "overflow": "hidden", "textOverflow": "ellipsis"},
            style_cell_conditional=[
                {"if": {"column_id": "plan_name"}, "minWidth": "200px",
                 "maxWidth": "280px"},
                {"if": {"column_id": "primary_care_copay"}, "maxWidth": "180px"},
                {"if": {"column_id": "generic_drug_copay"}, "maxWidth": "120px"},
                {"if": {"column_id": "metal_level"}, "minWidth": "70px"},
                {"if": {"column_id": "plan_type"}, "minWidth": "60px"},
            ],
            style_header={"fontWeight": "bold", "backgroundColor": "#f8f9fa"},
            style_data_conditional=[{"if": {"row_index": "odd"},
                                     "backgroundColor": "#fcfcfc"}],
            sort_action="native")