import sys
import inspect

sys.path.insert(0, r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend")
from services.sap_connector import SAPConnector

print(inspect.getsource(SAPConnector.read_object_source))
