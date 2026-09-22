import uuid
from collections import OrderedDict

_pending: "OrderedDict[str, tuple[str, str]]" = OrderedDict()
_LIMIT = 1000
def store(action: str, url: str) -> str:
    key = uuid.uuid4().hex  # 32 hex chars
    _pending[key] = (action, url)
    while len(_pending) > _LIMIT:
        _pending.popitem(last=False)
    return key
def pop(key: str):
    return _pending.pop(key, None)
