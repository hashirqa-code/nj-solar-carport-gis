"""Diagnose four NJ distributed-generation hosting-capacity map sources.

Public URLs only; emitted report is metadata, not utility confidential data.
"""
import json,requests,re,sys
from pathlib import Path
s=requests.Session()
s.headers.update({"User-Agent":"NJ-Solar-Carport-GIS-DueDiligence/1.0"})
sources={
"ACE_2026":"https://services3.arcgis.com/agWTKEK7X5K1Bx7o/ArcGIS/rest/services/PHI_Hosting_Capacity10_2_2026/FeatureServer/4",
"ORU_segmented":"https://services.arcgis.com/ciPnsNFi1JLWVjva/ArcGIS/rest/services/ORU_NodalHCV_Prod/FeatureServer/0",
"ORU_combined":"https://services.arcgis.com/ciPnsNFi1JLWVjva/ArcGIS/rest/services/IEDR_ORU/FeatureServer/10",
"ACE_prior":"https://services3.arcgis.com/agWTKEK7X5K1Bx7o/arcgis/rest/services/PHI_Hosting_Capacity_Public/FeatureServer/4",
}
def get(url,params={"f":"json"},timeout=17):
 try:
  r=s.get(url,params=params,timeout=timeout)
  if r.status_code>=400:return {"http":r.status_code,"error":r.text[:200]}
  if "json" not in r.headers.get("content-type","").lower():return {"http":r.status_code,"not_json":r.text[:130]}
  return r.json()
 except Exception as e:return {"error":str(e)[:210]}
report={"layers":{},"maps":{},"search":{}}
for key,url in sources.items():
 d=get(url)
 report["layers"][key]={"url":url,"error":d.get("error"),"http":d.get("http"),
    "id":d.get("id"),"name":d.get("name"),"geometryType":d.get("geometryType"),
    "fields":[{"name":f.get("name"),"alias":f.get("alias"),"type":f.get("type")} for f in d.get("fields",[])],
    "editingInfo":d.get("editingInfo")}
for key,id in {
"JCP_app":"d43cf2482a344e469eae6ca569403c24",
"JCP_older":"546e9834416b42aba00b30ce6f59cc5f",
"PSEG_older":"40cd14eeba9944ab82398e04bec5ab7a",
"ACE_older":"4ace7e2133ec4ecfb689f086669a5c8d"
}.items():
 item=get(f"https://www.arcgis.com/sharing/rest/content/items/{id}")
 dat=get(f"https://www.arcgis.com/sharing/rest/content/items/{id}/data")
 report["maps"][key]={"item":{k:item.get(k) for k in ("id","title","type","url","access","owner","modified","error")},"data_keys":list(dat.keys())[:22],
      "operationalLayers":[{"id":x.get("id"),"title":x.get("title"),"url":x.get("url"),"itemId":x.get("itemId")} for x in dat.get("operationalLayers",[])],
      "map":dat.get("map"),"data_error":dat.get("error")}
for key,url in {
"PSEG_web":"https://nj.pseg.com/saveenergyandmoney/solarandrenewableenergy/solarpowersustanibility",
"JCP_app_page":"https://firstenergycorp.maps.arcgis.com/apps/webappviewer/index.html?id=d43cf2482a344e469eae6ca569403c24"
}.items():
 try:
  r=s.get(url,timeout=15); txt=r.text
  found=re.findall(r"https?[^\s\"'<>]{8,180}(?:arcgis|FeatureServer|MapServer)[^\s\"'<>]{0,200}",txt,re.I)
  report["maps"][key]={"http":r.status_code,"url":r.url,"matched_urls":found[:15],"bytes":len(txt)}
 except Exception as e:report["maps"][key]={"error":str(e)[:210]}
# Newer first-party JCP transformer accommodation points, last updated June 2026
jcp="https://services9.arcgis.com/QhIvHlqYDjdoPWZG/arcgis/rest/services/Solar_Accommodation_Limit_2020/FeatureServer/0"
for name,url in {"JCP_2026_points":jcp}.items():
 m=get(url)
 sample=get(url+"/query",{"f":"json","where":"1=1","outFields":"*","returnGeometry":"false","resultRecordCount":4})
 report["layers"][name]={"url":url,"fields":[{"name":y.get("name"),"alias":y.get("alias")} for y in m.get("fields",[])],
    "geometryType":m.get("geometryType"),"lastEditDate":m.get("editingInfo",{}).get("lastEditDate"),
    "samples":[z.get("attributes") for z in sample.get("features",[])],"sampleError":sample.get("error")}
# ArcGIS Experience is PSEG's current NJ hosting application
eid="c28232df7cad40dfb9cf049c9cb97237"
for label,id in {"PSEG_Experience":eid}.items():
 it=get("https://www.arcgis.com/sharing/rest/content/items/"+id)
 dat=get("https://www.arcgis.com/sharing/rest/content/items/"+id+"/data")
 serialized=json.dumps(dat)
 found=re.findall(r'https?://[^"\\\\ ]{10,300}(?:FeatureServer|MapServer)(?:/\\d+)?',serialized)
 found2=re.findall(r'[a-f0-9]{32}',serialized)
 report["maps"][label]={"item":{k:it.get(k) for k in ("id","title","type","url","access","modified","error")},
   "data_keys":list(dat.keys()),"feature_url_hints":found[:25],"item_id_hints":list(dict.fromkeys(found2))[:45],
   "data_preview":serialized[:1500]}
# JCP public webmap ID is nested inside web application configuration
jdata=get("https://www.arcgis.com/sharing/rest/content/items/d43cf2482a344e469eae6ca569403c24/data")
report["maps"]["JCP_app_config"]={"map":jdata.get("map"),"dataSource":jdata.get("dataSource"),
 "url_hints":re.findall(r'https?://[^"\\\\ ]{10,250}(?:FeatureServer|MapServer)(?:/\\d+)?',json.dumps(jdata))[:20]}

# Resolve PSEG solar web map from ArcGIS Experience dataSource IDs
pseg=get("https://www.arcgis.com/sharing/rest/content/items/c28232df7cad40dfb9cf049c9cb97237/data")
report["maps"]["PSEG_data_sources"]={"dataSources":pseg.get("dataSources",{})}
ids=set()
def search_ids(obj):
 if isinstance(obj,dict):
  for k,v in obj.items():
   if k in ("itemId","webMapId","itemID","portalItemId") and isinstance(v,str) and re.fullmatch(r"[a-f0-9]{32}",v): ids.add(v)
   search_ids(v)
 elif isinstance(obj,list):
  for v in obj:search_ids(v)
search_ids(pseg)
for id in list(ids)[:18]:
 it=get("https://www.arcgis.com/sharing/rest/content/items/"+id)
 data=get("https://www.arcgis.com/sharing/rest/content/items/"+id+"/data")
 report["maps"]["PSEG_derived_"+id]={"item":{k:it.get(k) for k in ("id","title","type","url","access","modified","error")},
   "operationalLayers":[{"title":z.get("title"),"url":z.get("url"),"itemId":z.get("itemId")} for z in data.get("operationalLayers",[])],
   "url_hints":re.findall(r'https?://[^"\\\\ ]{10,250}(?:FeatureServer|MapServer)(?:/\\d+)?',json.dumps(data))[:20]}
# JCP webmap operational service references
it=get("https://www.arcgis.com/sharing/rest/content/items/06e89c8ad9c7441c944861aac5d1e54c")
data=get("https://www.arcgis.com/sharing/rest/content/items/06e89c8ad9c7441c944861aac5d1e54c/data")
report["maps"]["JCP_webmap"]={"item":{k:it.get(k) for k in ("id","title","type","url","modified")},
 "operationalLayers":[{"title":z.get("title"),"url":z.get("url"),"itemId":z.get("itemId")} for z in data.get("operationalLayers",[])]}

# Inspect fields and observed value ranges from currently linked first-party map layers.
for name,url in {
"PSEG_Generation_Capacity":"https://services.arcgis.com/yHb9HdkiNl1PZaOr/arcgis/rest/services/NM_HCM_ServicePoints/FeatureServer/1",
"PSEG_NetMetering_PSP":"https://services.arcgis.com/yHb9HdkiNl1PZaOr/arcgis/rest/services/NM_HCM_ServicePoints/FeatureServer/0",
"ACE_2026_samples":sources["ACE_2026"],
"ORU_segmented_samples":sources["ORU_segmented"],
}.items():
 m=get(url)
 sample=get(url+"/query",{"f":"json","where":"1=1","outFields":"*","returnGeometry":"false","resultRecordCount":4})
 report["layers"][name]={"url":url,"geometryType":m.get("geometryType"),
 "lastEditDate":m.get("editingInfo",{}).get("lastEditDate"),
 "fields":[{"name":y.get("name"),"alias":y.get("alias")} for y in m.get("fields",[])],
 "samples":[z.get("attributes") for z in sample.get("features",[])],
 "error":sample.get("error"),"http":m.get("http")}

for q in ['PSE&G solar suitability map','PSE&G hosting capacity New Jersey','JCP&L solar accommodation map','FirstEnergy New Jersey hosting capacity']:
 d=get("https://www.arcgis.com/sharing/rest/search",{"f":"json","q":q,"num":30},timeout=19)
 report["search"][q]=[{"id":x.get("id"),"title":x.get("title"),"type":x.get("type"),"url":x.get("url"),"modified":x.get("modified")} for x in d.get("results",[])[:12]]
Path("hosting_probe.json").write_text(json.dumps(report,indent=2))
print(json.dumps({k:{"status":v.get("http") or "ok","fields":[f["name"] for f in v.get("fields",[])]} for k,v in report["layers"].items()}))
