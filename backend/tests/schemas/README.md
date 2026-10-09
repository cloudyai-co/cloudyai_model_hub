# Vendored CycloneDX schemas

These files are copies of the official CycloneDX 1.6 JSON schemas and their
dependencies, taken from <https://github.com/CycloneDX/specification> at commit
`1ce97b2a7b8cf2429da248560d2aa671c6bce74a` (`schema/` directory). They are used by the test
suite to validate every generated AIBOM offline.

* `cyclonedx/bom-1.6.schema.json` (`$id` `http://cyclonedx.org/schema/bom-1.6.schema.json`)
* `cyclonedx/spdx.schema.json` (SPDX license identifiers)
* `cyclonedx/jsf-0.82.schema.json` (JSON signature format, referenced by the BOM schema)

The schemas are licensed under the Apache License 2.0; see `cyclonedx/LICENSE`.
Do not edit them by hand. To update, copy the newer files from upstream and update the commit above.
