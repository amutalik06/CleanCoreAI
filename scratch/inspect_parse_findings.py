import sys
import inspect

sys.path.insert(0, r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend")
from services.adt_client import ADTRestClient

print(inspect.getsource(ADTRestClient._parse_atc_findings))
