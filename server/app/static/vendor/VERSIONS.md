# Vendored frontend assets

Pinned, vendored (not npm-installed) per docs/WEB-PLAN.md §1 ("no Node build step in
the container"). Each subdirectory carries the upstream project's LICENSE file
verbatim. To upgrade: bump the version below, re-download from the same unpkg URLs,
and update this file.

| Library | Version | Files | Source |
|---|---|---|---|
| htmx | 2.0.4 | `htmx/htmx.min.js` | https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js |
| Leaflet | 1.9.4 | `leaflet/leaflet.js`, `leaflet/leaflet.css`, `leaflet/images/*` | https://unpkg.com/leaflet@1.9.4/dist/ |
| uPlot | 1.6.31 | `uplot/uPlot.iife.min.js`, `uplot/uPlot.min.css` | https://unpkg.com/uplot@1.6.31/dist/ |
