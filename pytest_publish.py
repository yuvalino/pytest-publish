from __future__ import annotations

import os
import traceback
from dataclasses import dataclass

import requests
from dataclasses_json import dataclass_json
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
    excinfo: ExcInfo | None = None  # not None if result is "skip" or "fail"


@hookimpl()
def pytest_addoption(parser: Parser):
    parser.addoption(
        "--publish",
        metavar="url",
        action="store",
        help="url to post test results",
    )


def create_result(item: Item, call: CallInfo, report: TestReport) -> TestResult:
    result = "pass"
    if call.excinfo:
        result = "skip" if call.excinfo.errisinstance(skip.Exception) else "fail"

    xdist_scope: str | None = None
    dist = item.config.getoption("dist", default=None)
    if dist:
        if dist == "loadgroup":
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
        xdist_dist=dist,
        xdist_worker=os.environ.get("PYTEST_XDIST_WORKER"),
        xdist_scope=xdist_scope,
    )

    if result != "pass":
        data.excinfo = TestResult.ExcInfo(
            type=call.excinfo.type.__name__,
            value=str(call.excinfo.value),
            traceback=traceback.format_tb(call.excinfo.tb),
        )

    return data


@hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: Item, call: CallInfo):
    report: TestReport = (yield).get_result()

    if not call.when == "call":
        return

    publish_url = item.config.getoption("publish")

    if not publish_url:
        return

    result = create_result(item, call, report)

    if publish_url:
        requests.post(publish_url, json=result.to_dict())  # type: ignore[attr-defined]
