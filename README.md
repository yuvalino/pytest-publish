# pytest-publish

pytest-publish is a simple pytest plugin for publishing test results mid-session.

Useful for live applications running on top of pytest (UI, logstash, etc).

## Usage

Only requirement is a target REST API endpoint to report test results to, e.g:
```sh
$ pytest --publish http://localhost:7777/test-update
```

On each test result, an HTTP POST request with the following JSON data will be submitted:
```python
{
    "type": "result",
    "result": ...,  # pass|fail|skip
    "nodeid": "<test item nodeid>",  # includes test name
    "start_time": 0.0,  # start time epoch seconds
    "stop_time": 0.1,   # end time epoch seconds
    "duration": 0.1,    # test duration seconds
    "stdout": "hello, world!",  # captured stdout
    "stderr": "WARN: ...", # captured stderr
    "log": "ERROR root:0:0 bad log",  # captured logs (logging lib)
    "xdist_worker": None or "gw0",  # worker name if running on xdist or None otherwise

    # only if "result" != "pass":
    "excinfo": {
        "type": "AssertionError", # exception type name
        "value": "assert False", # exception value string
        "traceback": [  # traceback lines
            "File .. in ..:\n  func()",
            "File .. in ..:\n  assert False"
        ]
    }
}
```
