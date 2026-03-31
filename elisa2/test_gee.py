# test_gee.py — run this ONCE to verify setup
import ee

SERVICE_ACCOUNT = "elisa-gee-runner@elisa-irrigation-research.iam.gserviceaccount.com"
KEY_FILE        = "./gee_key.json"

credentials = ee.ServiceAccountCredentials(SERVICE_ACCOUNT, KEY_FILE)
ee.Initialize(credentials)

# Test: fetch ERA5 SM for Meerut on one date
image = (
    ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
    .filterDate("2024-01-01", "2024-01-02")
    .first()
    .select("volumetric_soil_water_layer_1")
)
point = ee.Geometry.Point([77.70, 28.98])   # Meerut
value = image.reduceRegion(
    reducer=ee.Reducer.mean(), geometry=point, scale=9000
).getInfo()

print("ERA5 SM for Meerut on 2024-01-01:", value)
# Expected output: {'volumetric_soil_water_layer_1': 0.28...}