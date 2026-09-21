"""Initial workspace fixture for the human-review interface example."""


def version():
    return 200, {"data": {"version": "1.0"}, "error": None}


def lookup(records, key):
    if key not in records:
        return 404, {"data": None, "error": "not_found"}
    return 200, {"data": records[key], "error": None}
