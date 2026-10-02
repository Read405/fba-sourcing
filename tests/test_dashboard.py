"""The local HTML dashboard: empty state, demo data, escaping, and that demo
mode never touches the real history."""
import datetime as dt

from conftest import TODAY, make_candidate, run

from sourcing import db
from sourcing.dashboard import build_html, demo_data, render_split, write_dashboard
from sourcing.report import to_record


def test_empty_history_renders_empty_states(settings):
    page = build_html(settings, db.connect(":memory:"), TODAY)
    assert "No checks yet" in page
    assert "$420.01" in page                      # available capital hero
    assert "Black Friday Week and Cyber Monday 2026" in page
    assert "Shipping cost to Amazon ($/lb)" in page


def test_demo_has_every_verdict_and_leaves_real_settings_alone(settings):
    demo_settings, conn = demo_data(settings, TODAY)
    page = build_html(demo_settings, conn, TODAY, demo=True)
    for verdict in ("BUY", "CHECK MANUALLY", "WATCH", "REJECT"):
        assert verdict in page
    assert "Demo data" in page
    assert conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 7
    assert settings.config["unverified_costs"]["inbound_shipping_per_lb"]["value"] is None


def test_product_text_is_escaped(rated):
    conn = db.connect(":memory:")
    ev = run(rated, make_candidate({"title": "<script>alert(1)</script>"}))
    db.save_evaluation(conn, ev, to_record(ev))
    page = build_html(rated, conn, TODAY)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_money_split_shows_profit_and_costs(rated):
    data = to_record(run(rated, make_candidate()))["gates"][2]["data"]
    html = render_split(data)
    assert "Where the $29.99 sale price goes" in html
    assert "Profit" in html and "$6.72" in html and "$10.88" in html


def test_money_split_marks_a_loss(rated):
    data = to_record(run(rated, make_candidate({"purchase_price": 25.00})))["gates"][2]["data"]
    html = render_split(data)
    assert "are more than the $29.99 sale price" in html
    assert "sale-mark" in html and "Profit" not in html.split("legend")[1]


def test_write_dashboard_creates_file(settings, tmp_path):
    path = write_dashboard(settings, db.connect(":memory:"), TODAY, tmp_path / "dash.html")
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_calendar_drops_past_deadlines(settings):
    page = build_html(settings, db.connect(":memory:"), dt.date(2026, 10, 25))
    assert "Black Friday Week and Cyber Monday 2026" not in page
