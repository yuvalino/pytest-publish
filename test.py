import contextlib
import logging
import subprocess
import sys
import threading
from typing import List

import pytest
import requests
import werkzeug
from flask import Flask, request


@contextlib.contextmanager
def publish_mock_server(fn, port: int):
    rest_app = Flask("PublishMock")
    rest_server = werkzeug.serving.make_server("localhost", port, rest_app)
    rest_thread = threading.Thread(target=rest_server.serve_forever)

    @rest_app.route("/test-update", methods=["POST"])
    def test_update():
        fn(request.json)
        return ""

    rest_thread.start()
    try:
        yield
    finally:
        rest_server.shutdown()
        rest_thread.join()


def test_mockserver():
    port = 7777
    datas = list()
    with publish_mock_server(lambda x: datas.append(x), port):
        requests.post(f"http://localhost:{port}/test-update", json=dict(a=1))
    assert len(datas) == 1
    assert datas[0] == dict(a=1)


@contextlib.contextmanager
def publish_mock(cmdline: List[str], fn, port=7777):
    with publish_mock_server(fn, port):
        p = subprocess.Popen(
            cmdline + ["--publish", f"http://localhost:{port}/test-update"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            yield p
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
                raise ValueError("process has not exited")
            if p.poll() not in [0, 1]:
                stdout = "" if p.stdout is None else p.stdout.read().decode()
                raise ValueError(f"process did not succeed ({p.poll()}):\n{stdout}")


def run_tests(mark: str, fn, *args):
    with publish_mock(
        [
            "python3",
            "-m",
            "pytest",
            __file__,
            "-o",
            "python_functions='_test_*'",
            "-m",
            mark,
        ]
        + list(args),
        fn,
    ) as p:
        p.wait()


@pytest.mark.basic
def _test_basic():
    pass


def test_basic():
    datas = list()
    run_tests("basic", lambda x: datas.append(x))
    assert len(datas) == 1

    res = datas[0]
    assert res["type"] == "result"
    assert res["result"] == "pass"
    assert res["nodeid"] == "test.py::_test_basic"
    assert res["xdist_worker"] is None
    assert "excinfo" not in res


@pytest.mark.edgecase
def _test_fail():
    assert False


@pytest.mark.edgecase
def _test_skip():
    pytest.skip()


def test_edgecase():
    datas = list()
    run_tests("edgecase", lambda x: datas.append(x))
    assert len(datas) == 2

    fail, skip = datas
    assert fail["type"] == "result"
    assert fail["result"] == "fail"
    assert fail["excinfo"]["type"] == "AssertionError"
    assert fail["excinfo"]["value"] == "assert False"
    assert "in _test_fail" in fail["excinfo"]["traceback"][-1]
    assert "assert(False)" in fail["excinfo"]["traceback"][-1]

    assert skip["type"] == "result"
    assert skip["result"] == "skip"


@pytest.mark.capture
def _test_capture():
    print("it is")
    print("wednesday", file=sys.stderr)
    logging.warn("my doods")


def test_capture():
    datas = list()
    run_tests("capture", lambda x: datas.append(x))
    assert len(datas) == 1

    res = datas[0]
    assert res["stdout"] == "it is\n"
    assert res["stderr"] == "wednesday\n"
    assert "my doods" in res["log"]


@pytest.mark.xdist
@pytest.mark.parametrize("i", [str(x) for x in range(3)])
def _test_xdist(i):
    pass


def test_xdist():
    datas = list()
    run_tests("xdist", lambda x: datas.append(x), "-n2")
    assert len(datas) == 3

    res = datas[0]
    assert res["type"] == "result"
    assert res["result"] == "pass"
    assert res["nodeid"].startswith("test.py::_test_xdist[")
    assert res["xdist_worker"] in ["gw0", "gw1"]
    assert "excinfo" not in res
