"""SheetSentry - checks for business-critical spreadsheets."""

__version__ = "0.1.0"

from .finding import Finding, Severity  # noqa: F401
from .workbook import Book, load  # noqa: F401

__all__ = ["Finding", "Severity", "Book", "load", "__version__"]
