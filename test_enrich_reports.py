import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from shapely.geometry import box
from enrich_reports import parking_evidence,osm_query,write_xlsx

def _way(coords, tags, number=1):
    return {"type":"way","id":number,"tags":tags,
            "geometry":[{"lon":x,"lat":y} for x,y in coords]}

def test_osm_only_parking_follows_parcel_polygon():
    target=box(-74.61,40.34,-74.60,40.35)
    parking=box(-74.605,40.345,-74.601,40.349)
    nearby=box(-74.612,40.345,-74.611,40.349)
    xs=[
      _way(list(parking.exterior.coords),{"amenity":"parking","capacity":"65"},10),
      _way(list(nearby.exterior.coords),{"amenity":"parking","capacity":"500"},11),
      _way(list(parking.exterior.coords),{"amenity":"parking","parking":"multi-storey"},12)]
    v=parking_evidence(target,xs)
    assert v["osm_surface_parking_acres"]>0
    assert v["osm_parking_capacity_published"]==65
    assert "way/10" in v["osm_parking_feature_ids"]
    assert "way/11" not in v["osm_parking_feature_ids"]

def test_solar_in_parcel_is_flagged():
    g=box(-74.61,40.34,-74.60,40.35)
    sun=box(-74.608,40.347,-74.607,40.348)
    v=parking_evidence(g,[_way(list(sun.exterior.coords),{"power":"generator","generator:source":"solar"},90)])
    assert "SOLAR FEATURE" in v["osm_solar_warning"]
    assert not v["osm_parking_feature_ids"]

def test_xlsx_valid_openxml(tmp_path):
    p=tmp_path/"test.xlsx"
    write_xlsx(p,[("Solar Carport Leads",[["Rank","Address"],[1,"100 Main St"]],[12,28]),
                  ("Method and Audit",[["Field","Explanation"],["Stalls","Unknown"]],[20,30])])
    with zipfile.ZipFile(p) as z:
        assert z.testzip() is None
        tree=ET.fromstring(z.read("xl/workbook.xml"))
        ns={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        names=[node.attrib["name"] for node in tree.findall("m:sheets/m:sheet",ns)]
        assert names==["Solar Carport Leads","Method and Audit"]
        sheet=ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        assert len(sheet.findall("m:sheetData/m:row",ns))==2
