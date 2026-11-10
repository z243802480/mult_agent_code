import http.client
import json
from threading import Thread

import pytest

from boardkit.http_api import make_server
from boardkit.store import Store


@pytest.fixture
def api(tmp_path):
    store = Store(tmp_path / "api.db")
    server = make_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(method, path, payload=None, headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode() if payload is not None else None
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        connection.request(method, path, body, {"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        status = response.status
        if status != 204:
            assert "application/json" in response.getheader("Content-Type", "")
        connection.close()
        return status, json.loads(data) if data else None

    try:
        yield store, call
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_crud_and_shared_storage(api):
    store, call = api
    status, item = call("POST", "/tasks", {"title": " task ", "tags": ["B"]})
    assert status == 201 and item == store.get(item["id"])
    path = f'/tasks/{item["id"]}'
    assert call("GET", path) == (200, item)
    status, updated = call("PATCH", path, {"expected_version": 1, "status": "doing"})
    assert status == 200 and updated["version"] == 2 and updated["status"] == "doing"
    status, commented = call("POST", path + "/comments", {"expected_version": 2, "text": "note"})
    assert status == 201 and commented["version"] == 3
    assert call("DELETE", path, {"expected_version": 3}) == (204, None)
    status, error = call("GET", path)
    assert status == 404 and error["error"]["code"] == "not_found"


def test_http_idempotency_conflict(api):
    store, call = api
    headers = {"Idempotency-Key": "repeat-1"}
    status, first = call("POST", "/tasks", {"title": "one"}, headers)
    assert status == 201
    assert call("POST", "/tasks", {"title": "one"}, headers) == (201, first)
    status, error = call("POST", "/tasks", {"title": "two"}, headers)
    assert status == 409 and error["error"]["code"] == "conflict"
    assert store.list()["total"] == 1


def test_http_filters_and_pagination(api):
    store, call = api
    a = store.create("Alpha first", ["x"])
    b = store.create("Alpha next", ["x"])
    store.create("Beta", ["y"])
    status, page = call("GET", "/tasks?status=open&tag=X&q=alpha&limit=1&offset=1")
    assert status == 200 and page["total"] == 2
    assert [row["id"] for row in page["items"]] == [b["id"]]
    assert a["id"] < b["id"]


@pytest.mark.parametrize("method,path,payload,code", [
    ("GET", "/missing", None, 404),
    ("GET", "/tasks/999", None, 404),
    ("GET", "/tasks?limit=bad", None, 400),
    ("GET", "/tasks?offset=-1", None, 400),
    ("POST", "/tasks", {"title": ""}, 400),
    ("POST", "/tasks", b'{"title":', 400),
    ("POST", "/tasks", b'\xff', 400),
    ("POST", "/tasks", {"title": "x" * 66000}, 400),
    ("PATCH", "/tasks/999", {"expected_version": 1, "title": "x"}, 404),
])
def test_http_errors_are_structured(api, method, path, payload, code):
    _, call = api
    status, error = call(method, path, payload)
    assert status == code
    assert error["error"]["code"] in {"validation", "not_found"}
    assert isinstance(error["error"]["message"], str) and error["error"]["message"]
    assert "Traceback" not in json.dumps(error)


def test_http_conflict_does_not_mutate(api):
    store, call = api
    item = store.create("one")
    path = f'/tasks/{item["id"]}'
    status, error = call("PATCH", path, {"expected_version": 0, "title": "bad"})
    assert status in {400, 409}
    assert error["error"]["code"] in {"validation", "conflict"}
    assert store.get(item["id"]) == item
    store.update(item["id"], 1, title="two")
    status, error = call("DELETE", path, {"expected_version": 1})
    assert status == 409 and error["error"]["code"] == "conflict"
    assert store.get(item["id"])["title"] == "two"
