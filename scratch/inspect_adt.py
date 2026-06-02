import sys
import inspect

sys.path.insert(0, r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend")
from services.adt_client import ADTRestClient

print("Methods in ADTRestClient:")
for name, member in inspect.getmembers(ADTRestClient, predicate=inspect.isfunction):
    sig = inspect.signature(member)
    print(f"  {name}{sig}")
