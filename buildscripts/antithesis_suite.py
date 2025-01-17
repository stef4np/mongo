#!/usr/bin/env python3
"""Command line utility for generating suites for targeting antithesis."""

import os.path
import sys
import pathlib

import click
import yaml

# Get relative imports to work when the package is not installed on the PYTHONPATH.
if __name__ == "__main__" and __package__ is None:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SUITE_BLACKLIST = [
    "CheckReplDBHash",
    "CheckReplOplogs",
    "CleanEveryN",
    "ContinuousStepdown",
]


def _sanitize_hooks(hooks):
    if len(hooks) == 0:
        return hooks
    # it's either a list of strings, or a list of dicts, each with key 'class'
    if isinstance(hooks[0], str):
        return list(filter(lambda x: x not in SUITE_BLACKLIST, hooks))
    elif isinstance(hooks[0], dict):
        return list(filter(lambda x: x['class'] not in SUITE_BLACKLIST, hooks))
    else:
        raise RuntimeError('Unknown structure in hook. File a TIG ticket.')


_SUITES_PATH = os.path.join("buildscripts", "resmokeconfig", "suites")


@click.group()
def cli():
    """CLI Entry point."""
    pass


def _generate(suite_name: str) -> None:
    with open(os.path.join(_SUITES_PATH, "{}.yml".format(suite_name))) as fstream:
        suite = yaml.safe_load(fstream)

    try:
        suite["archive"]["hooks"] = _sanitize_hooks(suite["archive"]["hooks"])
    except KeyError:
        # pass, don't care
        pass
    except TypeError:
        pass

    try:
        suite["executor"]["archive"]["hooks"] = _sanitize_hooks(
            suite["executor"]["archive"]["hooks"])
    except KeyError:
        # pass, don't care
        pass
    except TypeError:
        pass

    try:
        suite["executor"]["hooks"] = _sanitize_hooks(suite["executor"]["hooks"])
    except KeyError:
        # pass, don't care
        pass
    except TypeError:
        pass

    out = yaml.dump(suite)
    with open(os.path.join(_SUITES_PATH, "antithesis_{}.yml".format(suite_name)), "w") as fstream:
        fstream.write(
            "# this file was generated by buildscripts/antithesis_suite.py generate {}\n".format(
                suite_name))
        fstream.write("# Do not modify by hand\n")
        fstream.write(out)


@cli.command()
@click.argument('suite_name')
def generate(suite_name: str) -> None:
    """Generate a single suite."""
    _generate(suite_name)


@cli.command('generate-all')
def generate_all():
    """Generate all suites."""
    for path in os.listdir(_SUITES_PATH):
        if os.path.isfile(os.path.join(_SUITES_PATH, path)):
            suite = path.split(".")[0]
            _generate(suite)


if __name__ == "__main__":
    cli()
