"""Athene's cluster pulse: the page's POST /cluster raises a pulse to Max.

Needs no browser, clips or Max.
"""

import time
import urllib.error
import urllib.request

from athene import live, render
from sitrep import pulse

from test_pulse import RecordingSender, values


def post(server, path):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    with urllib.request.urlopen(urllib.request.Request(url, method="POST")) as response:
        return response.status


def test_each_cluster_posted_is_its_own_pulse():
    sender = RecordingSender()
    cluster = pulse.Pulse(sender, address=live.CLUSTER, width=0.02)
    server = render.serve({}, 0, {"/cluster": cluster.fire})
    try:
        assert post(server, "/cluster") == 204
        time.sleep(0.2)
        assert post(server, "/cluster") == 204
        time.sleep(0.2)
    finally:
        server.shutdown()
    assert values(sender, live.CLUSTER) == [1, 0, 0, 1, 0, 0]


def test_a_post_to_another_path_is_not_found():
    server = render.serve({}, 0, {"/cluster": lambda: None})
    try:
        post(server, "/other")
    except urllib.error.HTTPError as error:
        assert error.code == 404
    else:
        raise AssertionError("expected 404")
    finally:
        server.shutdown()
