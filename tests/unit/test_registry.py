"""Drift guards for the crawler product registry.

If you add a product to PRODUCT_CRAWLERS, you MUST also add a sync wrapper
entry to PRODUCT_WRAPPERS — otherwise the CLI will see the product but not
be able to invoke it. Before v1.0.2 the CLI maintained its own copy of the
same dict, which drifted silently from the registry at least once. These
tests pin the invariant.
"""

from __future__ import annotations

import pytest

from bugdb.crawlers import PRODUCT_CRAWLERS, PRODUCT_WRAPPERS
from bugdb.crawlers.products.plugins import PLUGIN_CONFIGS


class TestProductRegistryConsistency:
    """PRODUCT_CRAWLERS and PRODUCT_WRAPPERS must stay in sync."""

    def test_every_crawler_has_a_wrapper(self):
        """Every entry in PRODUCT_CRAWLERS has a matching PRODUCT_WRAPPERS entry."""
        missing_wrappers = set(PRODUCT_CRAWLERS.keys()) - set(PRODUCT_WRAPPERS.keys())
        assert not missing_wrappers, (
            f"Products in PRODUCT_CRAWLERS with no sync wrapper in PRODUCT_WRAPPERS: "
            f"{sorted(missing_wrappers)}. Add a wrapper entry in "
            f"src/bugdb/crawlers/registry.py."
        )

    def test_every_wrapper_has_a_crawler(self):
        """Every entry in PRODUCT_WRAPPERS corresponds to a PRODUCT_CRAWLERS entry."""
        orphan_wrappers = set(PRODUCT_WRAPPERS.keys()) - set(PRODUCT_CRAWLERS.keys())
        assert not orphan_wrappers, (
            f"Sync wrappers in PRODUCT_WRAPPERS with no PRODUCT_CRAWLERS entry: "
            f"{sorted(orphan_wrappers)}. Either remove the wrapper or register "
            f"the crawler class in src/bugdb/crawlers/registry.py."
        )

    def test_product_ids_match_exactly(self):
        """The two dicts must have identical key sets."""
        assert set(PRODUCT_CRAWLERS.keys()) == set(PRODUCT_WRAPPERS.keys())

    def test_every_plugin_config_is_registered(self):
        """Every PLUGIN_CONFIGS entry must be registered in PRODUCT_CRAWLERS.

        Plugin crawlers all share the PluginCrawler class but register one
        product_id per plugin. A plugin config without a registry entry
        means the plugin exists on paper but is unreachable from the CLI.
        """
        missing_plugins = set(PLUGIN_CONFIGS.keys()) - set(PRODUCT_CRAWLERS.keys())
        assert not missing_plugins, (
            f"PLUGIN_CONFIGS entries not in PRODUCT_CRAWLERS: "
            f"{sorted(missing_plugins)}. Add a PRODUCT_CRAWLERS entry "
            f"mapping to PluginCrawler."
        )

    def test_wrappers_are_callable(self):
        """Every wrapper must be invocable — catches accidentally assigning a class."""
        for product_id, wrapper in PRODUCT_WRAPPERS.items():
            assert callable(wrapper), (
                f"PRODUCT_WRAPPERS[{product_id!r}] is not callable: {wrapper!r}"
            )


class TestRegistrySize:
    """Regression guards on the size of the registry itself."""

    def test_registry_is_non_empty(self):
        """Catches accidental full-wipe of the registry."""
        assert len(PRODUCT_CRAWLERS) > 0
        assert len(PRODUCT_WRAPPERS) > 0

    def test_expected_products_are_present(self):
        """Smoke test that the core products are still registered.

        Updates to this list are a conscious decision — shipping a release
        that silently dropped, say, 'panos' would be a disaster.
        """
        core_products = {
            "panos",
            "globalprotect",
            "cortex-xdr",
            "prisma-access",
            "prisma-access-agent",
            "prisma-sdwan",
            "scm",
            "cloud-ngfw-aws",
            "cloud-ngfw-azure",
        }
        missing_core = core_products - set(PRODUCT_CRAWLERS.keys())
        assert not missing_core, (
            f"Core products missing from PRODUCT_CRAWLERS: {sorted(missing_core)}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
