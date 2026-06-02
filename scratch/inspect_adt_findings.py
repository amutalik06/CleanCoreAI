import sys
import inspect

sys.path.insert(0, r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend")
from services.adt_client import ADTRestClient

src = inspect.getsource(ADTRestClient.get_atc_worklist_findings)
with open("adt_findings_source.txt", "w", encoding="utf-8") as f:
    f.write(src)
print("Saved to adt_findings_source.txt")
