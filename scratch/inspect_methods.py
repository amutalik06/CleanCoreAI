import sys
import inspect

sys.path.insert(0, r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend")
from services.adt_client import ADTRestClient

print("read_program_source implementation:")
print(inspect.getsource(ADTRestClient.read_program_source))
print("\nread_object_source implementation:")
print(inspect.getsource(ADTRestClient.read_object_source))
