"""FS quiz practice tooling and web app for the ISC Racing Team."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ifs-tests")
except PackageNotFoundError:
    __version__ = "0.0.0"
