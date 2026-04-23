from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from app.domain.models import MarketplaceMeta, ModalParseResult

SAVE_TOKEN_RE = re.compile(
    r"saveProduct\(\s*'[^']+'\s*,\s*'X-CSRF-TOKEN'\s*,\s*'([^']+)'\s*\)",
    re.IGNORECASE,
)


class ModalParser:
    """Parse the FOKS product modal HTML into a normalized domain structure."""

    MARKETPLACE_FIELD_RE = re.compile(r"(?P<field>[A-Za-z0-9_]+)\['(?P<market>[^']+)'\]")

    @staticmethod
    def parse(modal_html: str) -> ModalParseResult:
        """Extract form fields, marketplace data and metadata from the modal markup."""
        soup = BeautifulSoup(modal_html, "html.parser")
        form = soup.select_one("form#productForm")
        if not form:
            raise RuntimeError("productForm not found in modal HTML")

        basic_fields: dict[str, Any] = {}
        flags: dict[str, bool] = {}
        marketplace_fields: dict[str, dict[str, Any]] = {}
        market_cat_ids: dict[str, str] = {}
        market_cat_names: dict[str, str] = {}

        for el in form.find_all(["input", "textarea", "select"]):
            name = el.get("name")
            if not name:
                continue

            value: Any
            if el.name == "textarea":
                value = el.text or ""
            elif el.name == "select":
                selected = el.find("option", selected=True)
                value = selected.get("value", "") if selected else ""
            else:
                input_type = (el.get("type") or "").lower()
                if input_type == "checkbox":
                    value = el.has_attr("checked")
                else:
                    value = el.get("value", "")

            match = ModalParser.MARKETPLACE_FIELD_RE.fullmatch(name)
            if match:
                field_name = match.group("field")
                market_id = match.group("market")
                # Grouping marketplace-specific keys here keeps the upper layers free from regex-based lookups.
                marketplace_fields.setdefault(market_id, {})[field_name] = value
                if field_name == "marketCatIds":
                    market_cat_ids[market_id] = value or ""
                elif field_name == "marketCatNames":
                    market_cat_names[market_id] = value or ""
                continue

            if isinstance(value, bool):
                flags[name] = value
            else:
                basic_fields[name] = value

        marketplaces_meta: dict[str, MarketplaceMeta] = {}
        for pf in form.find_all("prod-features"):
            marketid = pf.get("marketid") or ""
            if not marketid:
                continue

            marketplaces_meta[marketid] = MarketplaceMeta(
                marketid=marketid,
                catid=pf.get("catid") or "",
                custcatid=pf.get("custcatid") or "",
            )

        extinfo_by_market: dict[str, Any] = {}
        for markup in form.find_all("prod-markup-info"):
            raw_extinfo = markup.get(":extinfo")
            if raw_extinfo:
                try:
                    # FOKS stores marketplace extinfo as a JSON string inside a Vue-style attribute.
                    extinfo_by_market = json.loads(raw_extinfo)
                    break
                except json.JSONDecodeError:
                    pass

        csrf_save_token = ""
        token_match = SAVE_TOKEN_RE.search(modal_html)
        if token_match:
            csrf_save_token = token_match.group(1)

        product_id = str(basic_fields.get("id") or "")
        offer_id = str(basic_fields.get("offerId") or "")

        if not product_id:
            raise RuntimeError("Product ID not found in modal form")

        return ModalParseResult(
            product_id=product_id,
            offer_id=offer_id,
            csrf_save_token=csrf_save_token,
            basic_fields=basic_fields,
            flags=flags,
            marketplace_fields=marketplace_fields,
            market_cat_ids=market_cat_ids,
            market_cat_names=market_cat_names,
            marketplaces_meta=marketplaces_meta,
            extinfo_by_market=extinfo_by_market,
        )
