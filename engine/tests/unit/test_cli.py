from typer.testing import CliRunner

from regateo.cli.main import app


def test_match_offline(tmp_path):
    db = tmp_path / "db"
    r = CliRunner().invoke(app, ["match", "--seller", "boulware", "--buyer", "scripted:linear", "--sim-clock",
                                 "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert "seller walk-away" in r.output and ("deal at" in r.output or "no deal" in r.output)
    r = CliRunner().invoke(app, ["runs", "--db", str(db)])
    assert r.exit_code == 0 and "match" in r.output
