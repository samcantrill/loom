"""Instantiate trusted target config into ordinary Python objects."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from weave import instantiate

from services import Formatter, Prefixer


def main() -> None:
    config = {
        "formatter": {
            "_target_": "services:Formatter",
            "prefixer": {
                "_target_": "services:Prefixer",
                "prefix": "item:",
            },
            "suffix": ".",
        },
        "joined": {
            "_target_": "services:join_values",
            "_args_": [["alpha", "beta", "gamma"]],
            "separator": " | ",
        },
        "joiner": {
            "_target_": "services:join_values",
            "_partial_": True,
            "separator": " / ",
        },
        "runtime_formatter": {
            "_target_": "services:Formatter",
            "_inject_": {"prefixer": "shared_prefixer"},
            "suffix": "!",
        },
    }

    objects = cast(
        dict[str, object],
        instantiate(
            config,
            runtime={"shared_prefixer": Prefixer("runtime:")},
        ),
    )
    joiner = objects["joiner"]
    if not isinstance(joiner, Callable):
        raise TypeError("joiner should be a callable partial")
    formatter = cast(Formatter, objects["formatter"])
    joined = cast(str, objects["joined"])
    typed_joiner = cast(Callable[[list[str]], str], joiner)
    runtime_formatter = cast(Formatter, objects["runtime_formatter"])

    print(formatter.render("42"))
    print(joined)
    print(typed_joiner(["one", "two"]))
    print(runtime_formatter.render("ready"))


if __name__ == "__main__":
    main()
