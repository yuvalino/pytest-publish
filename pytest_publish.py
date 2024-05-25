import os
import traceback

import requests
from pytest import CallInfo, Item, Parser, TestReport, hookimpl, skip


@hookimpl()
def pytest_addoption(parser: Parser):
    parser.addoption(
        "--publish",
        action="store",
        help="url to post test results",
    )


@hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: Item, call: CallInfo):
    report: TestReport = (yield).get_result()

    if not call.when == "call":
        return

    if not item.config.getoption("publish"):
        return

    result = "pass"
    if call.excinfo:
        result = "skip" if call.excinfo.errisinstance(skip.Exception) else "fail"

    data = {
        "type": "result",
        "result": result,
        "nodeid": item.nodeid,
        "start_time": call.start,
        "stop_time": call.stop,
        "duration": call.duration,
        "stdout": report.capstdout,
        "stderr": report.capstderr,
        "log": report.caplog,
        "xdist_worker": os.environ.get("PYTEST_XDIST_WORKER"),  # null if not xdist
    }

    if result != "pass":
        data.update(
            {
                "excinfo": {
                    "type": call.excinfo.type.__name__,
                    "value": str(call.excinfo.value),
                    "traceback": traceback.format_tb(call.excinfo.tb),
                }
            }
        )

    requests.post(item.config.getoption("publish"), json=data)
