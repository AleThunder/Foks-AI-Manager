from __future__ import annotations

import unittest

from fastapi import FastAPI

import main


class MainTests(unittest.TestCase):
    def test_main_exposes_fastapi_app(self) -> None:
        self.assertIsInstance(main.app, FastAPI)


if __name__ == "__main__":
    unittest.main()
