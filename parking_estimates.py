"""Reproducible preliminary surface-parking capacity estimates.

This is a DESK-SCREENING MODEL, not a computer-vision count of stalls.
When a parcel has only NJDEP 2015 'Other' pavement, a conservative share
factor by tax class / property use allocates an assumed parking portion.
When mapped OSM surface-parking polygons exist, treat their area as
a mapped lower-coverage anchor, not necessarily the entire lot.
Never describe modeled counts as verified parking spaces.
"""
import math

SQFT_PER_ACRE = 43560
# These are explicit analyst judgment scenarios, not empirical calibration
# or statutory parking requirements.
# low, central, high likely share of NJDEP 'Other impervious' area
USE_SHARES = {
    "parking_only": (0.65, 0.82, 0.95),
    "retail": (0.48, 0.68, 0.85),
    "office": (0.40, 0.60, 0.78),
    "medical": (0.47, 0.66, 0.82),
    "multifamily": (0.32, 0.52, 0.73),
    "institutional": (0.30, 0.53, 0.72),
    "industrial": (0.12, 0.30, 0.52),
    "religious": (0.36, 0.59, 0.80),
    "municipal": (0.24, 0.43, 0.68),
    "other_commercial": (0.30, 0.53, 0.78),
}
# The NYC/HQ labels are assessor use codes rather than zoning.
RETAIL_CODES = {"731","732","733","734","735","736","737","738"}
OFFICE_CODES = {"560","561","563","564","565","566"}
MEDICAL_CODES = {"271","562"}
PARKING_CODES = {"211","212"}
WAREHOUSE_CODES = {"950","951","952","953","954"}
INSTITUTION_CODES = {"660","661","662","663","664","665","666","667","668","669"}

def n(value):
    try:
        v=float(value)
        return v if math.isfinite(v) and v>=0 else 0.0
    except (TypeError,ValueError):
        return 0.0

def land_use_group(row):
    use=str(row.get("property_use") or "").strip()
    # Leading zeros are preserved for raw tax codes such as 029.
    tax=str(row.get("tax_class") or "").strip().upper()
    if use in PARKING_CODES:return "parking_only"
    if use in RETAIL_CODES:return "retail"
    if use in MEDICAL_CODES:return "medical"
    if use in OFFICE_CODES:return "office"
    if use in WAREHOUSE_CODES:return "industrial"
    if use in INSTITUTION_CODES:return "institutional"
    if tax=="4B":return "industrial"
    if tax=="4C":return "multifamily"
    if tax=="15A" or tax=="15B":return "institutional"
    if tax=="15C":return "municipal"
    if tax=="15D":return "religious"
    return "other_commercial"

def round10(v):
    if v<=0:return 0
    return max(10,int(math.floor(v/10.0+0.5))*10)

def estimate(row):
    """Return parking *capacity* estimate, not a verified stall inventory.

    1. OSM area >0.25 acres on a parcel: mapped parking polygons can be incomplete
       and may not distinguish covered/noncarport area; never infer full count solely
       from the partial map.
    2. Otherwise allocate an explicit percentage of NJDEP Other mixed pavement.
    3. 350/325/300 sqft per stall for low/central/high scenarios.
    """
    mixed=n(row.get("candidate_other_acres"))
    osm=n(row.get("osm_surface_parking_acres"))
    kind=land_use_group(row)
    lo,mid,hi=USE_SHARES[kind]
    sqft=lambda acres: acres*SQFT_PER_ACRE
    basis="NJDEP_2015_OTHER_PAVEMENT_WITH_ASSUMED_SHARE"
    evidence="VERY LOW — heuristic; parking footprint not isolated"
    if osm>=0.25:
        # OSM is an independent mapped footprint, but map completeness unknown.
        # Never assume ALL Other pavement is parking if OSM only maps a small lot.
        # The OSM minimum is a lower-range anchor, while base/high allow expansion
        # up to a land-use-specific portion of the mapped NJDEP pavement.
        lowarea=min(mixed,max(osm*0.75,mixed*lo*0.65)) if mixed else osm*.75
        basearea=min(mixed,max(osm,mixed*mid)) if mixed else osm
        higharea=min(mixed,max(osm*1.12,mixed*hi)) if mixed else osm*1.15
        basis="OSM_MAPPED_SURFACE_PARKING_PLUS_NJDEP_CONTEXT"
        evidence="LOW — mapped parking, unverified completeness and age"
    else:
        lowarea=mixed*lo
        basearea=mixed*mid
        higharea=mixed*hi
    if mixed<=0 and osm<=0:
        return {
          "parking_estimate_low":0,"parking_estimate_likely":0,"parking_estimate_high":0,
          "parking_estimate_method":"INSUFFICIENT_PAVEMENT_GEOMETRY",
          "parking_estimate_quality":"NO_ESTIMATE","estimated_parking_field_acres":0,
          "assumed_parking_share":0,"parking_land_use_group":kind,
          "estimated_largest_contiguous_row_capacity":0}
    low=round10(sqft(lowarea)/350)
    likely=round10(sqft(basearea)/325)
    high=round10(sqft(higharea)/300)
    low=min(low,likely)
    high=max(high,likely)
    largest=n(row.get("largest_other_piece_acres"))
    # This is an optimistic estimate of the largest uninterrupted *pavement*
    # component, not an actual contiguous parking row.
    contiguous=round10(sqft(largest*mid)/325)
    return {
       "parking_estimate_low":low,
       "parking_estimate_likely":likely,
       "parking_estimate_high":high,
       "parking_estimate_method":basis,
       "parking_estimate_quality":evidence,
       "assumed_parking_share":mid,
       "estimated_parking_field_acres":round(basearea,2),
       "parking_land_use_group":kind,
       "estimated_largest_contiguous_row_capacity":contiguous,
    }
