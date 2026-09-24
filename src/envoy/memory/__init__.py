"""Envoy's memory: the user's own past writing, imported from mail exports and
documents, or captured with consent, and searched when drafting.

- ``parse``: mbox and .eml files to plain records (stdlib only)
- ``clean``: quoted replies, signatures and HTML out of a message body
- ``importer``: walk paths, store messages and documents, report counts
"""

from .importer import ImportReport, import_paths

__all__ = ["ImportReport", "import_paths"]
