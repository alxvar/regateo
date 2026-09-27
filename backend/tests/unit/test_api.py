import pytest
from fastapi.testclient import TestClient

from regateo.api import create_app
from regateo.gym import GymSpec, run_gym
from regateo.storage import Store


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "db"
    store = await Store.open(path)
    spec = GymSpec.model_validate({"name": "api", "mode": "benchmark", "a": "boulware",
                                   "b": {"kind": "boulware", "name": "soft", "params": {"boulware": 1.5}},
                                   "opponents": ["scripted:liar"], "scenarios": {"per_cell": 3},
                                   "sim_clock": True})
    run_id, _ = await run_gym(spec, store)
    await store.close()
    return path, run_id


def test_endpoints(db, tmp_path):
    path, run_id = db
    with TestClient(create_app(path, ui_dir=tmp_path / "no-ui", poll_s=0.01)) as client:
        assert client.get("/api/overview").json()["matches"] == 12
        [run] = client.get("/api/runs").json()
        assert run["id"] == run_id and run["progress"]["done"] == 12
        report = client.get(f"/api/runs/{run_id}/report").json()
        assert report["kind"] == "gym" and report["report"]["diff"]["n"] == 6
        matches = client.get(f"/api/runs/{run_id}/matches").json()
        assert len(matches) == 12 and matches[0]["end_reason"]
        detail = client.get(f"/api/matches/{matches[0]['id']}").json()
        assert detail["messages"] and detail["match"]["scenario"]["seller_reservation"]
        stream = client.get(f"/api/matches/{matches[0]['id']}/stream").text
        assert stream.count("event: message") == len(detail["messages"]) and "event: end" in stream
        assert "event: end" in client.get(f"/api/runs/{run_id}/stream").text
        assert client.get("/api/runs/nope").status_code == 404


def test_serves_ui(db, tmp_path):
    path, _ = db
    ui = tmp_path / "dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(path, ui_dir=ui)) as client:
        assert client.get("/runs/abc").text == "<html>app</html>"       # client-side route
        assert client.get("/api/nope").status_code == 404
