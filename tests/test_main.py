from __future__ import annotations

import unittest

from fastapi import FastAPI

import main


class MainTests(unittest.TestCase):
    """Verify the top-level module exports the FastAPI application instance."""

    def test_main_exposes_fastapi_app(self) -> None:
        """Importing the entry module should expose a ready FastAPI app object."""
        self.assertIsInstance(main.app, FastAPI)


if __name__ == "__main__":
    unittest.main()
