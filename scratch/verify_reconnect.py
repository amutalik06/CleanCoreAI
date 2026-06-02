# verify_reconnect.py
# Tests the ADT XML namespace parsing and auto-reconnect connection cache functionality.

import sys
import os
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend dir is on path
backend_dir = r"C:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend"
sys.path.insert(0, backend_dir)

from config import settings
# Override upload dir for testing so the real SAP connection cache is untouched.
settings.UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "verify_reconnect_uploads")

from services.sap_connector import SAPConnector
from services.adt_client import ADTRestClient
from models import SAPConnectionConfig

import xml.etree.ElementTree as ET

def test_xml_parsing():
    xml_data = """<?xml version="1.0" encoding="utf-8"?>
    <search:results xmlns:search="http://www.sap.com/adt/repository/informationsystem" xmlns:adtcore="http://www.sap.com/adt/core">
        <adtcore:objectReference adtcore:name="ZTEST_ABAP_OBJECT" adtcore:type="PROG/P" adtcore:uri="/sap/bc/adt/programs/programs/ztest_abap_object" adtcore:packageName="ZCUSTOM" adtcore:description="Test Program"/>
    </search:results>
    """
    
    # We instantiate a temp client
    client = ADTRestClient(base_url="http://mock", client="100", user="test", password="pwd")
    parsed = client._parse_search_results(xml_data)
    
    assert len(parsed) == 1
    assert parsed[0]["name"] == "ZTEST_ABAP_OBJECT"
    assert parsed[0]["type"] == "PROG/P"
    assert parsed[0]["package"] == "ZCUSTOM"
    assert parsed[0]["description"] == "Test Program"
    print("[OK] XML Parsing test passed successfully!")

async def test_auto_reconnect():
    # Make sure test upload dir is clean
    if os.path.exists(settings.UPLOAD_DIR):
        shutil.rmtree(settings.UPLOAD_DIR)
        
    connector = SAPConnector()
    
    # Create mock configuration
    config = SAPConnectionConfig(
        adt_url="https://s4hana:44300",
        client="100",
        user="sap_user",
        passwd="secret_password",
        lang="EN",
        use_adt_fallback=True
    )
    
    # We will mock the adt client's connect method
    mock_adt = MagicMock()
    mock_adt.connect = AsyncMock(return_value={"system_id": "S4H", "system_name": "S4H", "release": "750", "host": "s4hana", "message": "Success"})
    mock_adt.close = AsyncMock()
    mock_adt.is_connected = True
    
    with patch("services.sap_connector.ADTRestClient", return_value=mock_adt):
        # 1. Connect
        status = await connector.connect(config)
        assert status.connected is True
        
        # Check that config file was written
        config_file = os.path.join(settings.UPLOAD_DIR, "sap_connection_config.json")
        assert os.path.exists(config_file)
        
        # 2. Reset connector state in memory (simulate server restart)
        connector._adt_client = None
        connector._connection_mode = ""
        
        # 3. Trigger _ensure_connected
        await connector._ensure_connected()
        
        # Check that it reconnected using cached config
        assert connector._connection_mode == "ADT"
        assert connector._adt_client is not None
        
        # 4. Test disconnect removes config file
        await connector.disconnect()
        assert not os.path.exists(config_file)
        
    print("[OK] Auto-reconnect test passed successfully!")

if __name__ == "__main__":
    import asyncio
    test_xml_parsing()
    asyncio.run(test_auto_reconnect())
    
    # Clean up
    if os.path.exists(settings.UPLOAD_DIR):
        shutil.rmtree(settings.UPLOAD_DIR)
