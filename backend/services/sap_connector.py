"""
CleanCore AI — SAP Connector Service
ADT REST API–first connectivity to SAP ECC/S4HANA.
PyRFC is an optional secondary fallback — no native SDK required by default.
"""
import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Optional, Dict, Any, List
from config import settings
from models import (
    SAPConnectionConfig, SAPConnectionStatus, ABAPObject,
    ATCFinding, FindingPriority, FindingCategory, InputSource,
    SAPATCResult, SAPPackageObject,
)
from services.adt_client import ADTRestClient, ADTError

logger = logging.getLogger("cleancore.sap_connector")


def _normalize_windows_env_path(path_value: str) -> str:
    """Repair Windows paths that dotenv may decode when they are quoted."""
    normalized = path_value.strip().strip('"').strip("'")
    if sys.platform.startswith("win"):
        normalized = (
            normalized
            .replace("\r\n", r"\n")
            .replace("\n", r"\n")
            .replace("\r", r"\r")
            .replace("\t", r"\t")
            .replace("\b", r"\b")
            .replace("\f", r"\f")
            .replace("\v", r"\v")
            .replace("\a", r"\a")
        )
    return normalized


# ─── ATC Finding Category Map ──────────────────────────────────────
CATEGORY_MAP = {
    "CL_CI_TEST_OPEN_SQL": FindingCategory.OPEN_SQL,
    "CL_CI_TEST_SELECT": FindingCategory.OPEN_SQL,
    "CL_CI_TEST_AMDP": FindingCategory.OPEN_SQL,
    "CL_SLIN_CHECK_DB": FindingCategory.OPEN_SQL,
    "CL_CI_TEST_TABLES": FindingCategory.OBSOLETE_TABLE,
    "CL_CI_TEST_DEPRECATED": FindingCategory.DEPRECATED_API,
    "CL_CI_TEST_DEPRECATED_STMNT": FindingCategory.DEPRECATED_STATEMENT,
    "CL_CI_TEST_MATNR": FindingCategory.MATNR_LENGTH,
}


def _map_priority(priority_str: str) -> FindingPriority:
    return {"1": FindingPriority.P1, "2": FindingPriority.P2}.get(
        priority_str, FindingPriority.P3
    )


def _map_category(check_id: str) -> FindingCategory:
    return CATEGORY_MAP.get(check_id, FindingCategory.GENERIC)


# ─── SAP Connector (ADT-first) ─────────────────────────────────────

class SAPConnector:
    """
    Manages connectivity to SAP systems.

    Primary path : ADT REST API over HTTPS (works through firewalls,
                   Cloud Connector, SAProuter — no native SDK required).
    Fallback     : PyRFC (requires SAP NW RFC SDK 7.50 installed locally).
    """

    def __init__(self):
        self._adt_client: Optional[ADTRestClient] = None
        self._rfc_connection = None
        self._config: Optional[SAPConnectionConfig] = None
        self._pyrfc_available = False
        self._pyrfc_error = ""
        self._sdk_error = ""
        self._dll_directory_handle = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sap-rfc")
        self._connect_lock = asyncio.Lock()
        self._ensure_lock = asyncio.Lock()
        self._connection_mode = ""  # "ADT" or "RFC"

        self._probe_pyrfc()

    # ─── PyRFC Probe (optional) ─────────────────────────────────────

    def _prepare_sdk_runtime(self) -> None:
        """Prepare SAP NW RFC SDK DLL/library lookup before importing pyrfc."""
        self._sdk_error = ""
        sapnwrfc_home = _normalize_windows_env_path(
            settings.SAPNWRFC_HOME or os.getenv("SAPNWRFC_HOME", "")
        )
        if not sapnwrfc_home:
            self._sdk_error = (
                "SAPNWRFC_HOME not set. PyRFC unavailable (ADT mode preferred)."
            )
            return

        sdk_root = Path(sapnwrfc_home)
        if not sdk_root.exists():
            self._sdk_error = f"SAPNWRFC_HOME path does not exist: {sdk_root}"
            return

        lib_dir = sdk_root / "lib"
        if not lib_dir.exists():
            self._sdk_error = f"SAP NW RFC SDK lib dir missing: {lib_dir}"
            return

        os.environ["SAPNWRFC_HOME"] = str(sdk_root)
        if (
            sys.platform.startswith("win")
            and lib_dir.exists()
            and self._dll_directory_handle is None
        ):
            self._dll_directory_handle = os.add_dll_directory(str(lib_dir))

    def _probe_pyrfc(self) -> None:
        """Try to load pyrfc — purely optional."""
        self._prepare_sdk_runtime()
        try:
            import pyrfc  # noqa: F401

            self._pyrfc_available = True
            self._pyrfc_error = ""
            self._sdk_error = ""
            logger.info("pyrfc available as optional fallback")
        except Exception as exc:
            self._pyrfc_available = False
            self._pyrfc_error = str(exc)
            logger.info(
                "pyrfc not available — ADT REST API will be used. %s",
                self._pyrfc_error,
            )

    # ─── Status / Diagnostics ───────────────────────────────────────

    async def runtime_status(self) -> Dict[str, Any]:
        """Return connectivity runtime readiness details for diagnostics."""
        await self._ensure_connected()
        sapnwrfc_home = _normalize_windows_env_path(
            settings.SAPNWRFC_HOME or os.getenv("SAPNWRFC_HOME", "")
        )
        sdk_root = Path(sapnwrfc_home) if sapnwrfc_home else None

        # Determine connection state
        is_connected = bool(self._adt_client and self._adt_client.is_connected) or bool(self._rfc_connection)

        return {
            "connection_mode": self._connection_mode or "not connected",
            "connected": is_connected,
            "adt_connected": bool(self._adt_client and self._adt_client.is_connected),
            "pyrfc_available": self._pyrfc_available,
            "sapnwrfc_home": sapnwrfc_home,
            "sapnwrfc_home_exists": bool(sdk_root and sdk_root.exists()),
            "sapnwrfc_lib_dir_exists": bool(
                sdk_root and (sdk_root / "lib").exists()
            ),
            "connect_timeout_seconds": settings.SAP_CONNECT_TIMEOUT_SECONDS,
            "rfc_call_timeout_seconds": settings.SAP_RFC_CALL_TIMEOUT_SECONDS,
            "sdk_error": self._sdk_error,
            "pyrfc_error": self._pyrfc_error,
            "message": (
                f"Connected via {self._connection_mode}"
                if self._connection_mode
                else "ADT REST API (HTTPS) — primary | PyRFC — optional fallback"
            ),
        }

    # ─── Connect ────────────────────────────────────────────────────

    async def connect(self, config: SAPConnectionConfig) -> SAPConnectionStatus:
        """
        Connect to SAP system.
        Strategy: ADT REST API first → PyRFC fallback.
        """
        self._config = config

        async with self._connect_lock:
            await self.disconnect(clear_cache=False)

            # ── Strategy 1: ADT REST API (preferred) ─────────────────
            adt_url = (config.adt_url or "").strip()
            adt_error_msg = ""
            rfc_msg = "PyRFC not attempted"

            if adt_url:
                logger.info("Connecting via ADT REST API: %s", adt_url)
                try:
                    self._adt_client = ADTRestClient(
                        base_url=adt_url,
                        client=config.client.strip(),
                        user=config.user.strip(),
                        password=config.passwd,
                        verify_ssl=getattr(config, "adt_verify_ssl", False),
                        timeout=settings.SAP_CONNECT_TIMEOUT_SECONDS,
                        lang=config.lang.strip() if config.lang else "EN",
                    )
                    info = await self._adt_client.connect()
                    self._connection_mode = "ADT"
                    self._save_connection_config(config)
                    return SAPConnectionStatus(
                        connected=True,
                        system_id=info.get("system_id", ""),
                        system_name=info.get("system_name", "S/4HANA"),
                        release=info.get("release", ""),
                        host=info.get("host", adt_url),
                        message=info.get("message", "Connected via ADT REST API"),
                    )
                except ADTError as exc:
                    logger.warning("ADT connection failed: %s", exc)
                    adt_error_msg = str(exc)
                    self._adt_client = None
                except Exception as exc:
                    logger.warning("ADT connection error: %s", exc)
                    adt_error_msg = str(exc)
                    self._adt_client = None
            else:
                adt_error_msg = (
                    "No ADT URL provided. Enter the base URL of your SAP system "
                    "(e.g. https://my-s4hana.example.com:44300)."
                )

            # ── Strategy 2: PyRFC fallback ───────────────────────────
            ashost = (config.ashost or "").strip()
            if self._pyrfc_available and ashost:
                logger.info("Falling back to PyRFC (ashost=%s)…", ashost)
                try:
                    connection, status = await self._run_blocking(
                        partial(self._connect_rfc_sync, config),
                        settings.SAP_CONNECT_TIMEOUT_SECONDS,
                    )
                    self._rfc_connection = connection
                    self._connection_mode = "RFC"
                    self._save_connection_config(config)
                    return status
                except asyncio.TimeoutError:
                    rfc_msg = f"RFC timed out after {settings.SAP_CONNECT_TIMEOUT_SECONDS:g}s"
                    logger.error(rfc_msg)
                except Exception as exc:
                    rfc_msg = f"RFC failed: {exc}"
                    logger.error(rfc_msg)
            elif not ashost:
                rfc_msg = "PyRFC skipped — no application server host (ashost) provided"
            else:
                rfc_msg = "PyRFC not available (NW RFC SDK not installed)"

            # ── Both failed ──────────────────────────────────────────
            if adt_error_msg and rfc_msg:
                combined = f"{adt_error_msg} | RFC fallback: {rfc_msg}"
            elif adt_error_msg:
                combined = adt_error_msg
            else:
                combined = rfc_msg
            return SAPConnectionStatus(connected=False, message=combined)

    # ─── RFC helpers ────────────────────────────────────────────────

    async def _run_blocking(self, func, timeout_seconds: float):
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(self._executor, func),
            timeout=timeout_seconds,
        )

    def _connect_rfc_sync(self, config: SAPConnectionConfig):
        import pyrfc

        ashost = (config.ashost or "").strip()
        if not ashost:
            raise ValueError("ashost is required for RFC connection")

        conn_params = {
            "ashost": ashost,
            "sysnr": (config.sysnr or "00").strip(),
            "client": (config.client or "100").strip(),
            "user": config.user.strip(),
            "passwd": config.passwd,
            "lang": (config.lang or "EN").strip(),
        }
        if config.saprouter and config.saprouter.strip():
            conn_params["saprouter"] = config.saprouter.strip()

        connection = pyrfc.Connection(**conn_params)
        result = connection.call("RFC_SYSTEM_INFO")
        sys_info = result.get("RFCSI_EXPORT", {})

        status = SAPConnectionStatus(
            connected=True,
            system_id=sys_info.get("RFCSYSID", ""),
            system_name=sys_info.get("RFCDBSYS", ""),
            release=sys_info.get("RFCDBREL", ""),
            host=sys_info.get("RFCHOST", config.ashost),
            message="Connected via PyRFC",
        )
        return connection, status

    async def _call_rfc(self, function_name: str, **kwargs):
        if not self._rfc_connection:
            raise ConnectionError("No RFC connection")
        try:
            return await self._run_blocking(
                partial(self._rfc_connection.call, function_name, **kwargs),
                settings.SAP_RFC_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"RFC call {function_name} timed out after "
                f"{settings.SAP_RFC_CALL_TIMEOUT_SECONDS:g}s"
            ) from exc

    # ─── Disconnect ─────────────────────────────────────────────────

    async def disconnect(self, clear_cache: bool = True):
        """Close all connections."""
        if self._adt_client:
            await self._adt_client.close()
            self._adt_client = None

        if self._rfc_connection:
            connection = self._rfc_connection
            self._rfc_connection = None
            try:
                await self._run_blocking(
                    connection.close, settings.SAP_RFC_CALL_TIMEOUT_SECONDS
                )
            except Exception as exc:
                logger.warning("Failed to close RFC connection: %s", exc)

        self._connection_mode = ""

        # Remove cached config only on explicit user disconnect.
        if clear_cache:
            config_path = os.path.join(settings.UPLOAD_DIR, "sap_connection_config.json")
            if os.path.exists(config_path):
                try:
                    os.remove(config_path)
                    logger.info("Removed cached SAP connection config on disconnect")
                except Exception as exc:
                    logger.error("Failed to remove cached SAP connection config: %s", exc)

    def _save_connection_config(self, config: SAPConnectionConfig):
        try:
            os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
            config_path = os.path.join(settings.UPLOAD_DIR, "sap_connection_config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(config.model_dump_json())
            logger.info("Saved SAP connection config to %s", config_path)
        except Exception as exc:
            logger.error("Failed to save SAP connection config: %s", exc)

    async def _ensure_connected(self):
        """Ensures that the connector is connected, reconnecting if configuration is cached."""
        if (self._adt_client and self._adt_client.is_connected) or self._rfc_connection:
            return

        async with self._ensure_lock:
            if (self._adt_client and self._adt_client.is_connected) or self._rfc_connection:
                return

            config_path = os.path.join(settings.UPLOAD_DIR, "sap_connection_config.json")
            if os.path.exists(config_path):
                logger.info("Connection lost or server restarted. Attempting auto-reconnect using cached config...")
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = f.read()
                    config = SAPConnectionConfig.model_validate_json(data)
                    status = await self.connect(config)
                    if status.connected:
                        logger.info("Auto-reconnect successful!")
                        return
                    logger.warning("Auto-reconnect failed: %s", status.message)
                except Exception as exc:
                    logger.error("Auto-reconnect failed with exception: %s", exc)

    # ─── Read Program Source ────────────────────────────────────────

    async def read_program_source(self, program_name: str) -> Optional[ABAPObject]:
        """Read ABAP program source code via ADT or RFC."""
        # ADT path
        if self._adt_client and self._adt_client.is_connected:
            try:
                source_code = await self._adt_client.read_program_source(program_name)
                return ABAPObject(
                    name=program_name,
                    type="PROG",
                    source_code=source_code,
                    line_count=len(source_code.split("\n")),
                    source=InputSource.SAP_RFC,
                )
            except ADTError as exc:
                logger.error("ADT read_program failed for %s: %s", program_name, exc)
                return None

        # RFC fallback
        if self._rfc_connection:
            try:
                result = await self._call_rfc(
                    "RPY_PROGRAM_READ",
                    PROGRAM_NAME=program_name,
                    WITH_LOWERCASE="X",
                )
                source_lines = result.get("SOURCE_EXTENDED", [])
                source_code = "\n".join(
                    [line.get("LINE", "") for line in source_lines]
                )
                program_attrs = result.get("PROG_INF", {})
                return ABAPObject(
                    name=program_name,
                    type=program_attrs.get("SUBC", "1"),
                    package=program_attrs.get("DEVCLASS", ""),
                    source_code=source_code,
                    line_count=len(source_lines),
                    source=InputSource.SAP_RFC,
                )
            except Exception as exc:
                logger.error("RFC read_program failed for %s: %s", program_name, exc)
                return None

        raise ConnectionError("Not connected to SAP system")

    # ─── Get Custom Objects ─────────────────────────────────────────

    async def get_custom_objects(self, namespace: str = "Z") -> List[Dict[str, str]]:
        """Get list of custom objects from the SAP repository."""
        # ADT path
        if self._adt_client and self._adt_client.is_connected:
            try:
                results = await self._adt_client.search_objects(
                    query=f"{namespace}*", max_results=5000
                )
                return [
                    {
                        "pgmid": "R3TR",
                        "object": r.get("type", ""),
                        "obj_name": r.get("name", ""),
                        "devclass": r.get("package", ""),
                    }
                    for r in results
                ]
            except ADTError as exc:
                logger.error("ADT search failed: %s", exc)
                return []

        # RFC fallback
        if self._rfc_connection:
            try:
                result = await self._call_rfc(
                    "RFC_READ_TABLE",
                    QUERY_TABLE="TADIR",
                    DELIMITER="|",
                    FIELDS=[
                        {"FIELDNAME": "PGMID"},
                        {"FIELDNAME": "OBJECT"},
                        {"FIELDNAME": "OBJ_NAME"},
                        {"FIELDNAME": "DEVCLASS"},
                    ],
                    OPTIONS=[
                        {"TEXT": f"OBJ_NAME LIKE '{namespace}%' AND PGMID = 'R3TR'"}
                    ],
                    ROWCOUNT=5000,
                )
                objects = []
                for row in result.get("DATA", []):
                    fields = row.get("WA", "").split("|")
                    if len(fields) >= 4:
                        objects.append({
                            "pgmid": fields[0].strip(),
                            "object": fields[1].strip(),
                            "obj_name": fields[2].strip(),
                            "devclass": fields[3].strip(),
                        })
                return objects
            except Exception as exc:
                logger.error("RFC get_custom_objects failed: %s", exc)
                return []

        raise ConnectionError("Not connected to SAP system")

    # ─── Read Function Module ───────────────────────────────────────

    async def read_function_module(self, fm_name: str) -> Optional[ABAPObject]:
        """Read function module source code."""
        if self._adt_client and self._adt_client.is_connected:
            try:
                source = await self._adt_client.read_function_module_source(fm_name)
                return ABAPObject(
                    name=fm_name,
                    type="FUGR",
                    source_code=source,
                    line_count=len(source.split("\n")),
                    source=InputSource.SAP_RFC,
                )
            except ADTError:
                return None

        if self._rfc_connection:
            try:
                result = await self._call_rfc(
                    "RFC_READ_FUNCTION_MODULE", FUNCTIONMODULE=fm_name
                )
                source_lines = result.get("SOURCE", [])
                source_code = "\n".join(
                    [line.get("LINE", "") for line in source_lines]
                )
                return ABAPObject(
                    name=fm_name,
                    type="FUGR",
                    source_code=source_code,
                    line_count=len(source_lines),
                    source=InputSource.SAP_RFC,
                )
            except Exception as exc:
                logger.error("RFC read_function_module failed: %s", exc)
                return None

        return None

    # ─── ATC Check ──────────────────────────────────────────────────

    async def run_atc_check(
        self, object_name: str, object_type: str = "PROG"
    ) -> List[ATCFinding]:
        """Run ATC check via ADT or return empty if unavailable."""
        if not self._adt_client or not self._adt_client.is_connected:
            logger.info("ATC check requires ADT connection — skipping")
            return []

        try:
            raw_findings = await self._adt_client.run_atc_check(
                object_name, object_type
            )
            findings: List[ATCFinding] = []
            for f in raw_findings:
                findings.append(
                    ATCFinding(
                        object_name=object_name,
                        check_id=f.get("checkId", ""),
                        check_title=f.get("checkTitle", ""),
                        message=f.get("message", ""),
                        line=f.get("line", 0),
                        column=f.get("column", 0),
                        priority=_map_priority(f.get("priority", "3")),
                        category=_map_category(f.get("checkId", "")),
                        sap_note=None,
                        quick_fix_available=f.get("quickFixAvailable", False),
                        raw_data=f,
                    )
                )
            return findings
        except Exception as exc:
            logger.error("ATC check failed for %s: %s", object_name, exc)
            return []

    # ─── New ATC and Package Connector Wrappers ──────────────────────

    async def read_object_source(self, object_name: str, object_type: str = "PROG") -> Optional[ABAPObject]:
        """Read source code of an ABAP object (PROG, CLAS, FUGR, etc.) via ADT or RFC."""
        await self._ensure_connected()
        object_type = object_type.upper().strip()
        
        # ADT Path
        if self._adt_client and self._adt_client.is_connected:
            try:
                source_code = await self._adt_client.read_object_source(object_name, object_type)
                return ABAPObject(
                    name=object_name,
                    type=object_type,
                    source_code=source_code,
                    line_count=len(source_code.split("\n")),
                    source=InputSource.SAP_RFC,
                )
            except Exception as exc:
                logger.error("ADT read_object_source failed for %s (%s): %s", object_name, object_type, exc)
                return None
                
        # RFC Path Fallback
        if self._rfc_connection:
            try:
                if object_type in ("PROG", "REPS", "1"):
                    return await self.read_program_source(object_name)
                elif object_type in ("FUGR", "FUNC"):
                    return await self.read_function_module(object_name)
                elif object_type == "CLAS":
                    class_prog = f"{object_name.upper():=<=30}CP"
                    return await self.read_program_source(class_prog)
                else:
                    return await self.read_program_source(object_name)
            except Exception as exc:
                logger.error("RFC read_object_source failed for %s (%s): %s", object_name, object_type, exc)
                return None
                
        raise ConnectionError("Not connected to SAP system")

    async def get_atc_results(self) -> List[SAPATCResult]:
        """Retrieve historical/central ATC check run results."""
        await self._ensure_connected()
        from datetime import datetime
        
        is_connected = bool(self._adt_client and self._adt_client.is_connected) or bool(self._rfc_connection)
        if not is_connected:
            raise ConnectionError("Not connected to SAP system")
            
        # ADT path
        if self._adt_client and self._adt_client.is_connected:
            try:
                raw_results = await self._adt_client.get_atc_results()
                return [
                    SAPATCResult(
                        id=r["id"],
                        title=r["title"],
                        timestamp=r["timestamp"],
                        object_set=r.get("object_set"),
                        findings_count=r.get("findings_count", 0),
                    )
                    for r in raw_results
                ]
            except Exception as exc:
                logger.error("ADT get_atc_results failed: %s", exc)
                if not self._rfc_connection:
                    raise RuntimeError(f"Failed to fetch ATC results from SAP: {exc}")
                
        # RFC fallback
        if self._rfc_connection:
            try:
                result = await self._call_rfc(
                    "RFC_READ_TABLE",
                    QUERY_TABLE="SATC_AC_RESULT",
                    DELIMITER="|",
                    FIELDS=[
                        {"FIELDNAME": "DISPLAY_ID"},
                        {"FIELDNAME": "TITLE"},
                        {"FIELDNAME": "CREATION_DATE"},
                        {"FIELDNAME": "CREATION_TIME"},
                        {"FIELDNAME": "OBJ_NAME"},
                    ],
                    ROWCOUNT=100,
                )
                results = []
                for row in result.get("DATA", []):
                    fields = row.get("WA", "").split("|")
                    if len(fields) >= 4:
                        display_id = fields[0].strip()
                        title = fields[1].strip()
                        date_str = fields[2].strip()
                        time_str = fields[3].strip()
                        obj_set = fields[4].strip() if len(fields) > 4 else ""
                        
                        ts = datetime.utcnow()
                        if date_str and time_str:
                            try:
                                ts = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
                            except Exception:
                                pass
                        
                        if display_id:
                            results.append(
                                SAPATCResult(
                                    id=display_id,
                                    title=title or f"ATC Run {display_id[:8]}",
                                    timestamp=ts,
                                    object_set=obj_set,
                                    findings_count=0,
                                )
                            )
                return results
            except Exception as exc:
                logger.error("RFC get_atc_results failed: %s", exc)
                raise RuntimeError(f"Failed to fetch ATC results from SAP: {exc}")
                
        raise ConnectionError("Not connected to SAP system")

    async def get_atc_worklist_findings(self, result_id: str) -> List[ATCFinding]:
        """Fetch all findings for a specific ATC worklist/result ID."""
        await self._ensure_connected()
        
        is_connected = bool(self._adt_client and self._adt_client.is_connected) or bool(self._rfc_connection)
        if not is_connected:
            raise ConnectionError("Not connected to SAP system")
            
        # ADT path
        if self._adt_client and self._adt_client.is_connected:
            try:
                raw_findings = await self._adt_client.get_atc_worklist_findings(result_id)
                findings = []
                for f in raw_findings:
                    findings.append(
                        ATCFinding(
                            object_name=f["object_name"],
                            object_type=f.get("object_type", "PROG"),
                            package_name=f.get("package_name", ""),
                            check_id=f.get("checkId", ""),
                            check_title=f.get("checkTitle", ""),
                            message=f.get("message", ""),
                            line=f.get("line", 0),
                            column=f.get("column", 0),
                            priority=_map_priority(f.get("priority", "3")),
                            category=_map_category(f.get("checkId", "")),
                            sap_note=None,
                            quick_fix_available=f.get("quickFixAvailable", False),
                            raw_data=f,
                        )
                    )
                return findings
            except Exception as exc:
                logger.error("ADT get_atc_worklist_findings failed: %s", exc)
                if not self._rfc_connection:
                    raise RuntimeError(f"Failed to fetch ATC findings: {exc}")
                
        # RFC fallback
        if self._rfc_connection:
            try:
                result = await self._call_rfc(
                    "RFC_READ_TABLE",
                    QUERY_TABLE="SATC_AC_FINDING",
                    DELIMITER="|",
                    FIELDS=[
                        {"FIELDNAME": "FINDING_ID"},
                        {"FIELDNAME": "TEST_CLASS_NAME"},
                        {"FIELDNAME": "CODE"},
                        {"FIELDNAME": "MSG"},
                        {"FIELDNAME": "PRIORITY"},
                    ],
                    OPTIONS=[{"TEXT": f"DISPLAY_ID = '{result_id.replace('-', '').upper()}'"}],
                    ROWCOUNT=500,
                )
                findings = []
                for row in result.get("DATA", []):
                    fields = row.get("WA", "").split("|")
                    if len(fields) >= 5:
                        finding_id = fields[0].strip()
                        test_class = fields[1].strip()
                        code = fields[2].strip()
                        msg = fields[3].strip()
                        priority_str = fields[4].strip()
                        
                        findings.append(
                            ATCFinding(
                                object_name="UNKNOWN",
                                check_id=test_class,
                                check_title=test_class,
                                message=msg,
                                line=1,
                                column=0,
                                priority=_map_priority(priority_str),
                                category=_map_category(test_class),
                                sap_note=None,
                                quick_fix_available=False,
                                raw_data={"finding_id": finding_id},
                            )
                        )
                return findings
            except Exception as exc:
                logger.error("RFC get_atc_worklist_findings failed: %s", exc)
                raise RuntimeError(f"Failed to fetch ATC findings: {exc}")
                
        raise ConnectionError("Not connected to SAP system")

    async def run_atc_on_package(self, package_name: str) -> Dict[str, Any]:
        """Trigger a fresh ATC check run on an entire SAP package."""
        await self._ensure_connected()
        if not self._adt_client or not self._adt_client.is_connected:
            raise ConnectionError("ATC run requires an ADT connection")
        return await self._adt_client.run_atc_on_package(package_name)

    async def get_objects_by_package(self, package_name: str) -> List[SAPPackageObject]:
        """List repository objects in a package."""
        await self._ensure_connected()
        
        is_connected = bool(self._adt_client and self._adt_client.is_connected) or bool(self._rfc_connection)
        if not is_connected:
            raise ConnectionError("Not connected to SAP system")
            
        # ADT path
        if self._adt_client and self._adt_client.is_connected:
            try:
                raw_objects = await self._adt_client.get_objects_by_package(package_name)
                return [
                    SAPPackageObject(
                        name=obj["name"],
                        type=obj.get("type", "PROG").split("/")[0],
                        package=package_name.strip().upper(),
                    )
                    for obj in raw_objects
                ]
            except Exception as exc:
                logger.error("ADT get_objects_by_package failed: %s", exc)
                if not self._rfc_connection:
                    raise RuntimeError(f"Failed to pull package objects: {exc}")
                
        # RFC fallback
        if self._rfc_connection:
            try:
                result = await self._call_rfc(
                    "RFC_READ_TABLE",
                    QUERY_TABLE="TADIR",
                    DELIMITER="|",
                    FIELDS=[
                        {"FIELDNAME": "OBJECT"},
                        {"FIELDNAME": "OBJ_NAME"},
                    ],
                    OPTIONS=[
                        {"TEXT": f"DEVCLASS = '{package_name.strip().upper()}' AND PGMID = 'R3TR'"}
                    ],
                    ROWCOUNT=1000,
                )
                objects = []
                for row in result.get("DATA", []):
                    fields = row.get("WA", "").split("|")
                    if len(fields) >= 2:
                        obj_type = fields[0].strip()
                        obj_name = fields[1].strip()
                        if obj_type in ("PROG", "CLAS", "INTF", "FUGR"):
                            objects.append(
                                SAPPackageObject(
                                    name=obj_name,
                                    type=obj_type,
                                    package=package_name.strip().upper(),
                                )
                            )
                return objects
            except Exception as exc:
                logger.error("RFC get_objects_by_package failed: %s", exc)
                raise RuntimeError(f"Failed to pull package objects: {exc}")
                
        raise ConnectionError("Not connected to SAP system")


# ─── Singleton Instance ─────────────────────────────────────────────
sap_connector = SAPConnector()
