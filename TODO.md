# TODO — SheetSentry

- [ ] Decide on PyPI publication (requires explicit Owner authorization; the
      package name is currently free) and a matching release workflow.
- [ ] After publication: consider GitHub Marketplace listing for the composite
      Action; align the package version with the shipped rule set (`diff` and
      the review workflow are already in `0.1.0` but were added after the
      initial release semantics) before any public release.
- [ ] Consider a `sheetsentry test` subcommand (currently a documented stub).
- [ ] Add lint/type checking and a coverage report to CI.
- [ ] Consider a `review` mode that understands multi-file envelopes
      (per-file extraction) without cross-file finding-ID collisions.
