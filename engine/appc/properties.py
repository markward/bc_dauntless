"""TGModelProperty hierarchy + manager.

See docs/superpowers/specs/2026-05-08-model-property-manager-design.md.
"""


class TGModelProperty:
    def __init__(self, name: str):
        self._name = name
        self._data: dict = {}

    def GetName(self) -> str:
        return self._name

    def SetName(self, value: str) -> None:
        self._name = value

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._name!r}>"

    def __getattr__(self, attr: str):
        if attr.startswith("Set"):
            field = attr[3:]
            data = self._data
            def setter(*args):
                data[(field, args[:-1])] = args[-1]
            return setter
        if attr.startswith("Get"):
            field = attr[3:]
            data = self._data
            def getter(*args):
                return data.get((field, args), None)
            return getter
        raise AttributeError(attr)
