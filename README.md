# pytest-publish

pytest-publish is a simple pytest plugin for publishing test results mid-session.

Useful for live applications running on top of pytest (UI, logstash, etc).

## Usage

There are 2 switches which can be turned on, each run every time a test has finished running:

1. `--publish <url>` to publish JSON reports to REST API.
2. `--pubdir <path>` to write results to filesystem.


### --publish

Run test like this:
```sh
$ pytest --publish http://localhost:7777/test-update
```

On each test result, an HTTP POST request with the following JSON data will be submitted:
```python
# from pytest_publish.py
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

```

### --pubdir

Run test like this:
```sh
$ pytest --pubdir /tmp/a
```

On each test result, the following directory tree will be created:
```sh
/tmp/a
/tmp/a/test_a
/tmp/a/test_a/.lock
/tmp/a/test_a/count
/tmp/a/test_a/0.pass               # <index>.<result> 
/tmp/a/test_a/0.pass/brief.txt     # textual description of result 
/tmp/a/test_a/0.pass/result.json   # same data as --publish
/tmp/a/test_a/0.pass/exception.txt # only if "skip" or "fail"
/tmp/a/test_a/0.pass/stdout.txt    # only if any stdout
/tmp/a/test_a/0.pass/stderr.txt    # only if any stderr
/tmp/a/test_a/0.pass/log.txt       # only if any logs
```

**NOTE:** If xdist's `--dist loadgroup` is run with xdist, the directory tree will look like this:
```sh
/tmp/a/<scope>
/tmp/a/<scope>/<test_name>
/tmp/a/<scope>/<test_name>/count
```
Notice the addition of the `<scope>` to the directory tree above.
