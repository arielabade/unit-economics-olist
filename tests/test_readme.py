"""No number may say one thing in the README and another on the dashboard.

Both are rendered from the committed tables in reports/. These tests fail
when either committed file is not what its renderer produces from reports/,
i.e. when someone edits a number by hand or forgets to regenerate.
"""

from unit_economics import dashboard, readme, reports
from unit_economics.config import ROOT


def test_readme_is_rendered_from_reports():
    committed = (ROOT / "README.md").read_text(encoding="utf-8")
    assert committed == readme.render(), "run `python -m unit_economics.readme`"


def test_dashboard_is_rendered_from_reports():
    committed = (ROOT / "docs" / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert committed == dashboard.render_page(), "run `python -m unit_economics.dashboard`"


def test_readme_and_dashboard_quote_the_same_headline():
    h = reports.headline_values()
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    page = (ROOT / "docs" / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert readme.times(h["paid_ltv_cac"]) in text
    assert dashboard.times(h["paid_ltv_cac"]) in page
    assert readme.pct(h["meta_spend_share"]) in text
    assert dashboard.pct(h["meta_spend_share"]) in page


def test_dashboard_ships_its_own_plotly_and_says_the_data_are_simulated():
    page = dashboard.render_page()
    plotly = page.split('data-plotly="')[1].split('"')[0]
    assert (ROOT / "docs" / "dashboard" / plotly).exists()
    for asset in ("app.js", "styles.css", "favicon.svg"):
        assert (ROOT / "docs" / "dashboard" / asset).exists()
    assert "Dados simulados" in page
    assert "https://cdn" not in page


def test_dashboard_assets_match_their_templates():
    for name in ("app.js", "styles.css"):
        built = (ROOT / "docs" / "dashboard" / name).read_bytes()
        assert built == (ROOT / "templates" / "dashboard" / name).read_bytes(), name


def test_dashboard_page_works_without_javascript():
    page = dashboard.render_page()
    # Every table twin is open in the HTML; only an inline script folds them.
    assert page.count('class="data-twin" open') == page.count('class="data-twin"')
    assert "<noscript>" in page
