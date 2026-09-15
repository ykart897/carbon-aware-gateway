# ENTSO-E parser fixtures

These are synthetic test documents, not downloaded measurements. Their element
names and production/consumption direction follow the ENTSO-E generation/load
model. Hourly and quarter-hour fixtures both represent 100 MWh solar plus
100 MWh coal; the latter also contains consumption that must be excluded.

References:

- [ENTSO-E generation/load document model and dependency table](https://eepublicdownloads.entsoe.eu/clean-documents/pre2015/resources/Transparency/MoP_Ref_05_-_gl-market-document_V3R0-2013-09-20.pdf)
- [ENTSO-E XML examples](https://gitlab.entsoe.eu/transparency/xml-examples)

The parser rejects incomplete fixed-interval curves, overlapping periods,
unknown units/types and differing time coverage rather than reporting a biased
generation-mix estimate. It does not estimate consumption-based emissions or
account for imports.
