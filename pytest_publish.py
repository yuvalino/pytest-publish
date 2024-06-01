from __future__ import annotations

import json
import math
import os
import traceback
from dataclasses import dataclass

import requests
from dataclasses_json import dataclass_json
from filelock import FileLock
from pytest import CallInfo, Item, Parser, TestReport, hookimpl, skip


@dataclass_json
@dataclass
class TestResult:
    @dataclass_json
    @dataclass
    class ExcInfo:
        type: str
        value: str
        traceback: list[str]

    type: str
    result: str  # "pass", "skip", "fail"
    nodeid: str
    start_time: float
    stop_time: float
    duration: float
    stdout: str
    stderr: str
    log: str
    xdist_dist: str | None  # only with xdist
    xdist_worker: str | None  # only with xdist
    xdist_scope: str | None  # only with xdist
    excinfo: ExcInfo | None = None  # only if "skip" or "fail"


@hookimpl()
def pytest_addoption(parser: Parser):
    parser.addoption(
        "--publish",
        metavar="url",
        action="store",
        help="url to post test results",
    )

    parser.addoption(
        "--pubdir",
        metavar="path",
        action="store",
        help="directory to post test results",
    )


def create_result(item: Item, call: CallInfo, report: TestReport) -> TestResult:
    result = "pass"
    if call.excinfo:
        result = "skip" if call.excinfo.errisinstance(skip.Exception) else "fail"

    # xdist-specific
    xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
    xdist_scope: str | None = None
    xdist_dist: str | None = None
    if xdist_worker:
        xdist_dist = item.config.workerinput["dist"]
        if xdist_dist == "loadgroup":
            from xdist.scheduler.loadgroup import LoadGroupScheduling

            xdist_scope = LoadGroupScheduling._split_scope(None, item.nodeid)

    data = TestResult(
        type="result",
        result=result,
        nodeid=item.nodeid,
        start_time=call.start,
        stop_time=call.stop,
        duration=call.duration,
        stdout=report.capstdout,
        stderr=report.capstderr,
        log=report.caplog,
        xdist_dist=xdist_dist,
        xdist_worker=xdist_worker,
        xdist_scope=xdist_scope,
    )

    if result != "pass":
        data.excinfo = TestResult.ExcInfo(
            type=call.excinfo.type.__name__,
            value=str(call.excinfo.value),
            traceback=traceback.format_tb(call.excinfo.tb),
        )

    return data


def pubdir(nodeid: str, pubdir_path: str, result: TestResult):
    # add scope dir (and potentially remove scope from `nodeid`)
    if result.xdist_scope:
        pubdir_path = os.path.join(pubdir_path, result.xdist_scope)
        scope_suffix = None
        if result.xdist_dist == "loadgroup":
            scope_suffix = f"@{result.xdist_scope}"

        if scope_suffix and nodeid.endswith(scope_suffix):
            nodeid = nodeid[: -len(scope_suffix)]

    # From this point forward, `pubdir_path` is `pubdir[/xdist_scope]/nodeid`
    pubdir_path = os.path.join(pubdir_path, nodeid)

    # Get unique test index (with filelock to support parallel execution of test)
    count = 0
    os.makedirs(pubdir_path, exist_ok=True)
    count_file = os.path.join(pubdir_path, "count")
    with FileLock(os.path.join(pubdir_path, ".lock")):
        if os.path.exists(count_file):
            with open(count_file, "r") as r:
                count_str = r.read().strip()
                if count_str.isdigit():
                    count = int(count_str)
        with open(count_file, "w") as w:
            w.write(str(count + 1))

    test_path = os.path.join(pubdir_path, f"{count}.{result.result}")
    os.makedirs(test_path)

    # Textual file for test result
    with open(os.path.join(test_path, "brief.txt"), "w") as w:

        def _print(str: str, file=None):
            for f in [w] + ([] if not file else [file]):
                print(str.rstrip(), file=f)

        def _header(title) -> str:
            width = 66 - len(title) - 2
            if width <= 2:
                return title
            return (
                ("=" * math.ceil(float(width) / 2))
                + f" {title} "
                + ("=" * math.floor(float(width) / 2))
            )

        _print(_header("general test info"))
        _print(f"test: {nodeid}")
        if result.xdist_scope:
            _print(f"xdist-scope: {result.xdist_scope}")
        _print(f"result: {result.result}")
        _print(f"duration: {result.duration}s")
        if result.xdist_worker:
            _print(f"xdist-node: {result.xdist_worker}")
        if result.xdist_dist and result.xdist_dist != "no":
            _print(f"xdist-dist: {result.xdist_dist}")

        if result.excinfo:
            _print(_header("exception"))
            with open(os.path.join(test_path, "exception.txt"), "w") as w2:
                _print("".join(result.excinfo.traceback), file=w2)
                if result.excinfo.value:
                    _print(f"{result.excinfo.type}: {result.excinfo.value}", file=w2)
                else:
                    _print(f"{result.excinfo.type}", file=w2)

        if result.stdout:
            _print(_header("stdout"))
            with open(os.path.join(test_path, "stdout.txt"), "w") as w2:
                _print(result.stdout, file=w2)

        if result.stderr:
            _print(_header("stderr"))
            with open(os.path.join(test_path, "stderr.txt"), "w") as w2:
                _print(result.stderr, file=w2)

        if result.log:
            _print(_header("log"))
            with open(os.path.join(test_path, "log.txt"), "w") as w2:
                _print(result.log, file=w2)

    with open(os.path.join(test_path, "result.json"), "w") as w:
        w.write(json.dumps(result.to_dict(), indent=4))  # type: ignore[attr-defined]


@hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: Item, call: CallInfo):
    report: TestReport = (yield).get_result()

    if not call.when == "call":
        return

    publish_url = item.config.getoption("publish")
    pubdir_path = item.config.getoption("pubdir")

    if not publish_url and not pubdir_path:
        return

    result = create_result(item, call, report)

    if publish_url:
        requests.post(publish_url, json=result.to_dict())  # type: ignore[attr-defined]

    item.session.items

    if pubdir_path:
        # calculate if long or short nodeid
        # NOTE: can be cached to save time
        nodeid = result.nodeid.split("::")[-1]
        if any(
            x
            for x in item.session.items
            if x.nodeid.endswith(nodeid) and x.nodeid != result.nodeid
        ):
            nodeid = result.nodeid

        pubdir(nodeid, pubdir_path, result)


@hookimpl(optionalhook=True)
def pytest_configure_node(node):
    node.workerinput["dist"] = node.config.getoption("dist")
