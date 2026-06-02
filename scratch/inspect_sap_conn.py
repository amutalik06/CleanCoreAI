import sys
import inspect

sys.path.insert(0, r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend")
from services.sap_connector import SAPConnector

print("Methods in SAPConnector:")
for name, member in inspect.getmembers(SAPConnector, predicate=inspect.isfunction):
    sig = inspect.signature(member)
    print(f"  {name}{sig}")
