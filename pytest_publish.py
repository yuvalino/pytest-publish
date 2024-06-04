from __future__ import annotations

import json
import math
import os
import traceback
from dataclasses import dataclass

import requests
from dataclasses_json import dataclass_json
from filelock import FileLock
from pytest import CallInfo, Config, Item, Parser, TestReport, hookimpl, skip


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
    name: str
    start_time: float
    stop_time: float
    duration: float
    stdout: str
    stderr: str
    log: str
    xdist_dist: str | None  # only with xdist
    xdist_worker: str | None  # only with xdist
    xdist_scope: str | None  # only with xdist
    pubdir_path: str | None  # only with --pubdir
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

    parser.addoption(
        "--pubdir-filter",
        action="store",
        choices=["all", "bad", "fail"],
        default="bad",
        help="filter which tests are written to directory",
    )


def generate_test_pubdir_path(
    pubdir_path: str, test_name: str, result: str, xdist_scope: str | None
):
    if xdist_scope:
        pubdir_path = os.path.join(pubdir_path, xdist_scope)
    # TODO: dual test names
    pubdir_path = os.path.join(pubdir_path, test_name)

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

    return os.path.join(pubdir_path, f"{count}.{result}")


def should_pubdir_test(config: Config, result: str) -> bool:
    pubdir_filter = config.getoption("pubdir_filter")
    if pubdir_filter == "all":
        return True
    if pubdir_filter == "fail":
        return result == "fail"
    return result != "pass"


def create_result(
    item: Item, call: CallInfo, report: TestReport, pubdir_path: str | None
) -> TestResult:
    result = "pass"
    if call.excinfo:
        result = "skip" if call.excinfo.errisinstance(skip.Exception) else "fail"

    nodeid: str = item.nodeid
    name: str = nodeid.split("::")[-1]

    # xdist-specific
    xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
    xdist_scope: str | None = None
    xdist_dist: str | None = None
    if xdist_worker:
        xdist_dist = item.config.workerinput["dist"]
        if xdist_dist == "loadgroup":
            from xdist.scheduler.loadgroup import LoadGroupScheduling

            xdist_scope = LoadGroupScheduling._split_scope(None, nodeid)
            name = name[: name.rfind("@")]

    # set destination file in pubdir
    test_pubdir_path = None
    if pubdir_path:
        # NOTE: always generate so we write to `count` file
        path = generate_test_pubdir_path(pubdir_path, name, result, xdist_scope)
        if should_pubdir_test(item.config, result):
            test_pubdir_path = path

    data = TestResult(
        type="result",
        result=result,
        nodeid=nodeid,
        name=name,
        start_time=call.start,
        stop_time=call.stop,
        duration=call.duration,
        stdout=report.capstdout,
        stderr=report.capstderr,
        log=report.caplog,
        xdist_dist=xdist_dist,
        xdist_worker=xdist_worker,
        xdist_scope=xdist_scope,
        pubdir_path=test_pubdir_path,
    )

    if result != "pass":
        data.excinfo = TestResult.ExcInfo(
            type=call.excinfo.type.__name__,
            value=str(call.excinfo.value),
            traceback=traceback.format_tb(call.excinfo.tb),
        )

    return data


def pubdir(result: TestResult):
    if not result.pubdir_path:
        return

    os.makedirs(result.pubdir_path, exist_ok=True)

    # Textual file for test result
    with open(os.path.join(result.pubdir_path, "brief.txt"), "w") as w:

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
        _print(f"test: {result.nodeid}")
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
            with open(os.path.join(result.pubdir_path, "exception.txt"), "w") as w2:
                _print("".join(result.excinfo.traceback), file=w2)
                if result.excinfo.value:
                    _print(f"{result.excinfo.type}: {result.excinfo.value}", file=w2)
                else:
                    _print(f"{result.excinfo.type}", file=w2)

        if result.stdout:
            _print(_header("stdout"))
            with open(os.path.join(result.pubdir_path, "stdout.txt"), "w") as w2:
                _print(result.stdout, file=w2)

        if result.stderr:
            _print(_header("stderr"))
            with open(os.path.join(result.pubdir_path, "stderr.txt"), "w") as w2:
                _print(result.stderr, file=w2)

        if result.log:
            _print(_header("log"))
            with open(os.path.join(result.pubdir_path, "log.txt"), "w") as w2:
                _print(result.log, file=w2)

    with open(os.path.join(result.pubdir_path, "result.json"), "w") as w:
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

    result = create_result(item, call, report, pubdir_path)

    pubdir(result)

    if publish_url:
        requests.post(publish_url, json=result.to_dict())  # type: ignore[attr-defined]


@hookimpl(optionalhook=True)
def pytest_configure_node(node):
    node.workerinput["dist"] = node.config.getoption("dist")
