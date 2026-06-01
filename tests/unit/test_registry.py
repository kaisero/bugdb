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


class TestCrawlerConstructorKwargs:
    """Every registered crawler class must accept the BaseCrawler kwarg
    contract that the CLI threads through the registry — so a subclass
    overriding ``__init__`` without forwarding a kwarg (the historical
    ``PluginCrawler`` bug) fails here instead of at the first real
    fetch."""

    REQUIRED_KWARGS: tuple[str, ...] = (
        "headless",
        "debug",
        "max_concurrency",
        "max_retries",
        "retry_delay",
        "discovery_cache",
        "reporter",
        "task",
    )

    def test_every_crawler_init_accepts_required_kwargs(self):
        """Introspect the constructor signature of every crawler class.

        The CLI / registry constructs crawlers with a fixed kwarg set
        including ``discovery_cache``, ``reporter``, and ``task``. Any
        subclass override that drops one of those will raise
        ``TypeError: unexpected keyword argument`` at runtime. This
        test catches that statically so the failure mode is "import-
        time pytest fail" instead of "mid-crawl explosion on the 13th
        product".
        """
        import inspect

        failures: list[str] = []
        for product_id, cls in sorted(PRODUCT_CRAWLERS.items()):
            sig = inspect.signature(cls.__init__)
            params = sig.parameters
            # If the subclass takes **kwargs, every name is accepted
            # by definition — that's the PANOSCrawler pattern.
            accepts_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if accepts_var_keyword:
                continue
            missing = [kw for kw in self.REQUIRED_KWARGS if kw not in params]
            if missing:
                failures.append(f"{product_id} ({cls.__name__}): missing kwargs {missing}")

        assert not failures, (
            "One or more crawler __init__ overrides are missing required "
            "kwargs from the BaseCrawler contract. The registry will raise "
            "TypeError at runtime when it tries to construct these. Fix by "
            "adding the missing kwarg(s) and forwarding to super().__init__:\n"
            + "\n".join(f"  - {f}" for f in failures)
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
