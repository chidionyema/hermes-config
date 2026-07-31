# Prospector baseline — 2026-07-31 04:24

**HEAD:** `b21a3ca` (branch discovery-ux-2026-07-30)
**Command:** `python3 -m pytest tests --ignore=tests/control_center -q`
**Verdict:** 11 failed, 662 passed, 2 skipped

## Collection note
`tests/control_center/*` — 6 collection ERRORs (excluded from baseline).

## Module line counts (vetting)
```
     215 /Users/chidionyema/Documents/code/prospector/prospector/prescreen.py
      62 /Users/chidionyema/Documents/code/prospector/prospector/kill_filter.py
      61 /Users/chidionyema/Documents/code/prospector/prospector/score.py
     130 /Users/chidionyema/Documents/code/prospector/prospector/novelty.py
      95 /Users/chidionyema/Documents/code/prospector/prospector/pass_ceiling.py
     346 /Users/chidionyema/Documents/code/prospector/prospector/golden.py
     909 total
```

## Failures (names)
```
FAILED tests/test_engine_bridge.py::TestProviderSelection::test_stripe_provider_selected_via_config
FAILED tests/test_engine_bridge.py::TestStripeProvisionerHardening::test_create_price_passes_idempotency_key
FAILED tests/test_engine_bridge.py::TestStripeProvisionerHardening::test_create_product_passes_idempotency_key
FAILED tests/test_engine_bridge.py::TestStripeProvisionerHardening::test_stripe_error_becomes_provisioning_error
FAILED tests/test_ui_theme.py::TestThemeCSS::test_theme_module_exists_and_exports_inject
FAILED tests/test_ui_theme.py::TestThemeCSS::test_theme_css_is_non_trivial_string
FAILED tests/test_ui_theme.py::TestThemeCSS::test_inject_theme_does_not_raise
FAILED tests/test_ui_theme.py::TestOverviewPage::test_overview_module_imports
FAILED tests/test_ui_theme.py::TestOverviewPage::test_overview_has_card_render_functions
FAILED tests/unit/test_retrieval_resilience.py::test_ddg_retries_transient_error_then_succeeds
FAILED tests/unit/test_retrieval_resilience.py::test_ddg_gives_up_after_three_transient_errors
```
