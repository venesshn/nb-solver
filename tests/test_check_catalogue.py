import copy
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from check_catalogue import losses

from nbsolver.scrape import http

CATALOGUE = {
    "missions": [
        {
            "slug": "e7034",
            "sources": ["blazingonline", "hideoutgacha"],
            "unit_boosts": [],
            "stages": [
                {
                    "stage_id": 703402,
                    "name": "Stage",
                    "maps": [
                        {
                            "number": 1,
                            "grid": {"columns": 9, "rows": 7},
                            "sets": [{"enemies": [{"name": "Zetsu"}]}],
                        }
                    ],
                }
            ],
        }
    ]
}


def test_an_identical_rebuild_loses_nothing():
    assert losses(CATALOGUE, copy.deepcopy(CATALOGUE)) == []


def test_a_dropped_layout_and_source_are_refused():
    # What a single dropped connection did to e7034 in the first weekly refresh.
    after = copy.deepcopy(CATALOGUE)
    mission = after["missions"][0]
    mission["sources"] = ["blazingonline"]
    mission["stages"][0]["maps"][0]["grid"] = None
    found = losses(CATALOGUE, after)
    assert any("layout" in f for f in found)
    assert any("hideoutgacha" in f for f in found)


def test_missing_missions_stages_and_maps_are_refused():
    after = copy.deepcopy(CATALOGUE)
    after["missions"][0]["stages"][0]["maps"] = []
    assert any("whole map" in f for f in losses(CATALOGUE, after))
    after["missions"][0]["stages"] = []
    assert any("whole stage" in f for f in losses(CATALOGUE, after))
    assert any("whole mission" in f for f in losses(CATALOGUE, {"missions": []}))


def test_additions_pass():
    after = copy.deepcopy(CATALOGUE)
    after["missions"].append({"slug": "new", "stages": []})
    after["missions"][0]["sources"].append("fandom")
    assert losses(CATALOGUE, after) == []


def _client(replies):
    def handler(request):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(reply, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_retries_a_dropped_connection_and_a_server_error():
    replies = [httpx.RemoteProtocolError("Server disconnected"), 503, 200]
    with _client(replies) as client:
        assert http.get(client, "https://x/", pause=0).status_code == 200
    assert replies == []


def test_fetch_does_not_retry_a_missing_page():
    replies = [404, 200]
    with _client(replies) as client, pytest.raises(httpx.HTTPStatusError):
        http.get(client, "https://x/", pause=0)
    assert replies == [200]
