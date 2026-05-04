"""Instantiate trusted target config into ordinary Python objects."""

from __future__ import annotations

from collections.abc import Callable

from loom.config import instantiate

from services import Prefixer


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

    objects = instantiate(
        config,
        runtime={"shared_prefixer": Prefixer("runtime:")},
    )
    joiner = objects["joiner"]
    if not isinstance(joiner, Callable):
        raise TypeError("joiner should be a callable partial")

    print(objects["formatter"].render("42"))
    print(objects["joined"])
    print(joiner(["one", "two"]))
    print(objects["runtime_formatter"].render("ready"))


if __name__ == "__main__":
    main()

