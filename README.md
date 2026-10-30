# New Jersey Solar-Carport GIS Screening

A scheduled, auditable **preliminary** parcel-screening system for Promittens Energy. It queries the NJGIN tax-parcel/MOD-IV composite and the NJDEP 2015 **Other impervious** polygons, spatially clips the returned pavement geometries to each qualifying tax parcel, and computes preliminary surface-area proxies.

**Do not interpret proxy space-equivalents as parking-stall counts or buildable solar-carport capacity.** The NJDEP Other layer can include driveways, sidewalks, loading areas and misclassified building roofs where LiDAR was unavailable. It is historical (2015). Before contacting a landowner or designing a project, manually verify recent orthophotography, existing solar projects, parcel ownership, carport layout, permitting, wetlands, and current utility hosting capacity.

## Status and workflow

- Automated GitHub Actions schedule: Monday–Friday at approximately **8:00 AM America/New_York**. GitHub schedules are not exact guarantees and may run late.
- The workflow also runs on pushes to the source files and supports manual dispatch.
- It runs offline regression tests, attempts live NJGIN/NJDEP GIS calls from GitHub-hosted compute, and writes auditable results to `daily_reports/`.
- State in `daily_reports/state.json` tracks which provisional candidate assessor locations and parcels have been surfaced. **40 previously reported properties** are preseeded in `seed_excluded_addresses.txt`.
- New outputs, when available, are `YYYY-MM-DD_provisional_parcels.csv`, `YYYY-MM-DD_addresses_UNVERIFIED.txt`, and `YYYY-MM-DD_audit.json`. Runs upload the output as a GitHub Actions artifact.
- Individual parcel failures are recorded. If all live queries fail, the job fails rather than silently presenting synthetic geometries.
- Current scanner does **not** create 20 independently verified property leads, count striped parking stalls from imagery, confirm utility hosting MW, or send outreach. It builds a prioritization list requiring secondary due diligence.
- Current geometry is a grid/paginated screening prototype, not a finished statewide exhaustive database. Work remains on per-tile retry coverage, current aerial counting, entity ownership, and direct delivery integration.

## Sources

- NJGIN parcels + MOD-IV: https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0
- NJDEP 2015 impervious surface: https://mapsdep.nj.gov/arcgis/rest/services/Cached_Layers/Rast_impervious_surface_3857/MapServer/0
- 2020 state aerial imagery for manual verification: https://maps.nj.gov/arcgis/rest/services/Basemap/Orthos_Natural_2020_NJ_WM/MapServer

## Run

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python pipeline.py --out daily_reports --tiles 2 --per-tile 12 --max-results 20
```

Review the dated audit before trusting the CSV. Assessor property locations can differ from verified postal street addresses. GIS boundaries are not legal surveys. Hosted GitHub Actions execution does not automatically publish these results into the separate ChatGPT scheduled-task conversation.
