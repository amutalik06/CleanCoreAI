"""
CleanCore AI — SAP ADT REST API Client
Full-featured client for ABAP Development Tools (ADT) REST APIs.
Connects over standard HTTPS — no SAP NW RFC SDK required.
"""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, Dict, Any, List
from urllib.parse import quote

import httpx

logger = logging.getLogger("cleancore.adt_client")

# ─── XML Namespaces used by ADT ────────────────────────────────────
NS = {
    "adtcore": "http://www.sap.com/adt/core",
    "atc": "http://www.sap.com/adt/atc",
    "atom": "http://www.w3.org/2005/Atom",
    "program": "http://www.sap.com/adt/programs/programs",
    "class": "http://www.sap.com/adt/oo/classes",
    "search": "http://www.sap.com/adt/repository/informationsystem",
}

SOURCE_SUPPORTED_OBJECT_TYPES = {"PROG", "INCL", "CLAS", "INTF", "FUGR", "FUNC"}


def _simple_object_type(adt_type: str) -> str:
    raw_type = adt_type.upper().strip()
    if raw_type == "PROG/I":
        return "INCL"
    if raw_type == "FUGR/FF":
        return "FUNC"
    return raw_type.split("/")[0] if raw_type else ""


def _source_supported(adt_type: str) -> bool:
    return _simple_object_type(adt_type) in SOURCE_SUPPORTED_OBJECT_TYPES


class ADTError(Exception):
    """Raised when an ADT API call fails."""

    def __init__(self, message: str, status_code: int = 0, detail: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class ADTRestClient:
    """
    Session-based ADT REST API client.

    Maintains a persistent httpx.AsyncClient with cookie jar for stateful
    ADT sessions. CSRF tokens are fetched once and refreshed automatically
    on 403 responses.

    Key design decisions:
    - The base httpx client does NOT carry an X-CSRF-Token default header,
      because the token value changes after the first Fetch call and default
      headers cannot be overridden per-request in all httpx versions.
    - CSRF is injected explicitly on every mutating request via req_headers.
    - sap-client and sap-language are sent on every request.
    """

    def __init__(
        self,
        base_url: str,
        client: str,
        user: str,
        password: str,
        verify_ssl: bool = False,
        timeout: float = 30.0,
        lang: str = "EN",
    ):
        self.base_url = base_url.rstrip("/")
        self.sap_client = client
        self.user = user
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.lang = lang

        self._csrf_token: str = ""
        self._http: Optional[httpx.AsyncClient] = None
        self._connected: bool = False
        self._system_info: Dict[str, str] = {}

    # ─── Lifecycle ──────────────────────────────────────────────────

    async def _ensure_client(self):
        """Lazily create the underlying HTTP client.

        Important: We do NOT set X-CSRF-Token as a default header here,
        because we need to send 'Fetch' for the token discovery call but
        then use the actual token value for subsequent requests.  Mixing
        this in default headers causes the token value to be stale on all
        non-mutating requests and can confuse some SAP systems.
        """
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                auth=(self.user, self.password),
                verify=self.verify_ssl,
                timeout=httpx.Timeout(self.timeout, connect=15.0),
                follow_redirects=True,
                headers={
                    # Permanent per-session headers — no CSRF here
                    "sap-client": self.sap_client,
                    "sap-language": self.lang,
                    "Accept-Language": self.lang,
                },
            )

    async def close(self):
        """Close the underlying HTTP session."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None
        self._connected = False
        self._csrf_token = ""

    # ─── CSRF Token ─────────────────────────────────────────────────

    async def _fetch_csrf_token(self) -> str:
        """
        Fetch a CSRF token from the ADT discovery endpoint.

        SAP ADT requires a valid X-CSRF-Token for all POST/PUT/DELETE calls.
        We retrieve it by issuing a GET with 'X-CSRF-Token: Fetch' and reading
        the token back from the response header.
        """
        await self._ensure_client()
        assert self._http is not None

        try:
            # ADT discovery endpoint requires application/atomsvc+xml (Atom Service Document).
            # Using application/xml causes HTTP 406 Not Acceptable on most SAP systems.
            resp = await self._http.get(
                "/sap/bc/adt/discovery",
                headers={
                    "X-CSRF-Token": "Fetch",
                    "Accept": "application/atomsvc+xml",
                    "sap-client": self.sap_client,
                    "sap-language": self.lang,
                },
            )
            token = resp.headers.get("x-csrf-token", "")
            if token and token.lower() not in ("", "required", "fetch"):
                self._csrf_token = token
                logger.debug("CSRF token acquired (len=%d)", len(token))
            else:
                logger.debug(
                    "CSRF token header value was '%s' (HTTP %d)",
                    token,
                    resp.status_code,
                )
        except httpx.HTTPError as exc:
            logger.warning("CSRF fetch failed: %s", exc)

        return self._csrf_token

    # ─── Low-Level Request ──────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[str] = None,
        params: Optional[Dict[str, str]] = None,
        accept: str = "application/xml",
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """
        Execute an ADT REST request with auto CSRF handling.
        Retries once on 403 (token expired).
        """
        await self._ensure_client()
        assert self._http is not None

        # Ensure we have a CSRF token before any mutating request
        mutating = method.upper() in ("POST", "PUT", "DELETE", "PATCH")
        if mutating and not self._csrf_token:
            await self._fetch_csrf_token()

        req_headers: Dict[str, str] = {
            "Accept": accept,
            "sap-client": self.sap_client,
            "sap-language": self.lang,
        }
        if mutating and self._csrf_token:
            req_headers["X-CSRF-Token"] = self._csrf_token
        if headers:
            req_headers.update(headers)

        req_timeout = httpx.Timeout(timeout, connect=15.0) if timeout is not None else httpx.Timeout(self.timeout, connect=15.0)

        resp = await self._http.request(
            method, path, headers=req_headers, content=content, params=params, timeout=req_timeout
        )

        # Auto-refresh CSRF on 403
        if resp.status_code == 403 and mutating:
            logger.info("CSRF token rejected (403) — refreshing")
            self._csrf_token = ""
            await self._fetch_csrf_token()
            if self._csrf_token:
                req_headers["X-CSRF-Token"] = self._csrf_token
            resp = await self._http.request(
                method, path, headers=req_headers, content=content, params=params, timeout=req_timeout
            )

        return resp

    # ─── Connection & System Info ───────────────────────────────────

    async def connect(self) -> Dict[str, Any]:
        """
        Verify connectivity and retrieve system information.

        Strategy:
        1. Ensure the HTTP client exists.
        2. Fetch CSRF token via GET /sap/bc/adt/discovery — this also
           proves the credentials are accepted (401 → ADTError).
        3. Try GET /sap/bc/adt/core/discovery for rich system info.
        4. Fall back to just confirming /sap/bc/adt/discovery is reachable.
        """
        try:
            await self._ensure_client()

            # Step 1: Fetch CSRF token + validate basic ADT reachability.
            # IMPORTANT: /sap/bc/adt/discovery requires Accept: application/atomsvc+xml
            # (Atom Service Document format). Sending application/xml causes HTTP 406.
            # A 401 here means wrong credentials; 404 means ADT not activated.
            resp_discovery = await self._http.get(  # type: ignore[union-attr]
                "/sap/bc/adt/discovery",
                headers={
                    "X-CSRF-Token": "Fetch",
                    "Accept": "application/atomsvc+xml",
                    "sap-client": self.sap_client,
                    "sap-language": self.lang,
                },
            )

            if resp_discovery.status_code == 401:
                raise ADTError(
                    "Authentication failed — check user/password and SAP client.",
                    status_code=401,
                    detail=resp_discovery.text[:200],
                )
            if resp_discovery.status_code == 404:
                raise ADTError(
                    "ADT service not found at this URL. Verify the ADT base URL and that "
                    "the ICF service /sap/bc/adt is active in the system.",
                    status_code=404,
                )
            if resp_discovery.status_code == 406:
                raise ADTError(
                    "ADT discovery returned HTTP 406 Not Acceptable. "
                    "This usually means the ICF path /sap/bc/adt is correct but "
                    "the port or URL path prefix may be wrong. "
                    "Try port 44300 (standard HTTPS) instead of the current port.",
                    status_code=406,
                    detail=resp_discovery.text[:400],
                )
            if resp_discovery.status_code not in (200, 201, 204):
                raise ADTError(
                    f"ADT discovery returned HTTP {resp_discovery.status_code}. "
                    f"Response: {resp_discovery.text[:300]}",
                    status_code=resp_discovery.status_code,
                )

            # Capture the CSRF token from the discovery response
            token = resp_discovery.headers.get("x-csrf-token", "")
            if token and token.lower() not in ("", "required", "fetch"):
                self._csrf_token = token

            # Step 2: Try to get richer system info from core/discovery
            system_info: Dict[str, str] = {"host": self.base_url}
            try:
                resp_core = await self._http.get(  # type: ignore[union-attr]
                    "/sap/bc/adt/core/discovery",
                    headers={
                        "Accept": "application/xml",
                        "sap-client": self.sap_client,
                        "sap-language": self.lang,
                    },
                )
                if resp_core.status_code == 200:
                    system_info = self._parse_system_info(resp_core.text)
                else:
                    logger.debug(
                        "core/discovery returned HTTP %d — using basic info",
                        resp_core.status_code,
                    )
            except httpx.HTTPError as exc:
                logger.debug("core/discovery request failed: %s — using basic info", exc)

            self._system_info = system_info
            self._connected = True
            logger.info("ADT connection established to %s", self.base_url)
            return {
                "connected": True,
                "system_id": system_info.get("system_id", ""),
                "system_name": system_info.get("system_name", "S/4HANA"),
                "release": system_info.get("release", ""),
                "host": self.base_url,
                "message": "Connected via ADT REST API (HTTPS)",
            }

        except ADTError:
            raise
        except httpx.ConnectError as exc:
            raise ADTError(
                f"Cannot reach SAP system at {self.base_url}: {exc}. "
                "Check the ADT URL, network/firewall, and Cloud Connector settings."
            ) from exc
        except httpx.TimeoutException as exc:
            raise ADTError(
                f"Connection to {self.base_url} timed out after {self.timeout}s. "
                "The system may be overloaded or unreachable."
            ) from exc
        except Exception as exc:
            raise ADTError(f"ADT connection failed: {exc}") from exc

    def _parse_system_info(self, xml_text: str) -> Dict[str, str]:
        """Extract system info from the core discovery XML."""
        info: Dict[str, str] = {"host": self.base_url}
        try:
            root = ET.fromstring(xml_text)
            # Try to find relevant system attributes
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                text = (elem.text or "").strip()
                if tag == "systemId" and text:
                    info["system_id"] = text
                elif tag == "systemType" and text:
                    info["system_name"] = text
                elif tag == "release" and text:
                    info["release"] = text
        except ET.ParseError:
            logger.warning("Could not parse core discovery XML")
        return info

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ─── Repository Search ──────────────────────────────────────────

    async def search_objects(
        self,
        query: str = "Z*",
        object_type: str = "",
        max_results: int = 200,
    ) -> List[Dict[str, str]]:
        """
        Search the ABAP repository for objects matching a pattern.
        Uses /sap/bc/adt/repository/informationsystem/search
        """
        params: Dict[str, str] = {
            "operation": "quickSearch",
            "query": query,
            "maxResults": str(max_results),
        }
        if object_type:
            params["objectType"] = object_type

        resp = await self._request(
            "GET",
            "/sap/bc/adt/repository/informationsystem/search",
            params=params,
        )

        if resp.status_code != 200:
            logger.warning("Search failed: HTTP %d", resp.status_code)
            return []

        return self._parse_search_results(resp.text)

    def _parse_search_results(self, xml_text: str) -> List[Dict[str, str]]:
        """Parse ADT search result XML into a list of object dicts."""
        results: List[Dict[str, str]] = []
        try:
            root = ET.fromstring(xml_text)
            for obj_ref in root.iter():
                tag = obj_ref.tag.split("}")[-1] if "}" in obj_ref.tag else obj_ref.tag
                if tag == "objectReference":
                    # Extract attributes by removing namespace prefixes
                    attribs = {}
                    for k, v in obj_ref.attrib.items():
                        local_key = k.split("}")[-1] if "}" in k else k
                        attribs[local_key] = v.strip()  # SAP may pad values with whitespace
                    name = attribs.get("name", "").strip()
                    obj_type = attribs.get("type", "").strip()
                    if not name:
                        continue  # skip empty entries
                    results.append({
                        "name": name,
                        "type": obj_type,
                        "uri": attribs.get("uri", "").strip(),
                        "package": attribs.get("packageName", attribs.get("package", "")).strip(),
                        "description": attribs.get("description", "").strip(),
                    })
        except ET.ParseError:
            logger.warning("Could not parse search results XML")
        return results

    # ─── Read Source Code ───────────────────────────────────────────

    async def read_program_source(self, program_name: str) -> str:
        """Read ABAP program source code."""
        name = program_name.strip().lower()
        resp = await self._request(
            "GET",
            f"/sap/bc/adt/programs/programs/{quote(name, safe='')}/source/main",
            accept="text/plain",
        )

        if resp.status_code == 200:
            return resp.text
        elif resp.status_code == 404:
            raise ADTError(f"Program '{program_name}' not found", status_code=404)
        else:
            raise ADTError(
                f"Failed to read program '{program_name}': HTTP {resp.status_code}",
                status_code=resp.status_code,
                detail=resp.text[:500],
            )

    async def read_class_source(self, class_name: str) -> str:
        """Read ABAP class source code (public section + implementation)."""
        name = class_name.strip().lower()
        parts: List[str] = []

        for section in ["source/main"]:
            resp = await self._request(
                "GET",
                f"/sap/bc/adt/oo/classes/{quote(name, safe='')}/{section}",
                accept="text/plain",
            )
            if resp.status_code == 200:
                parts.append(resp.text)

        if not parts:
            raise ADTError(f"Class '{class_name}' not found or empty", status_code=404)

        return "\n".join(parts)

    async def read_function_module_source(self, fm_name: str) -> str:
        """
        Read function module source code.
        The URI pattern is /sap/bc/adt/functions/groups/{group}/fmodules/{fm}/source/main
        but we can also try the direct FM path.
        """
        name = fm_name.strip().lower()
        resp = await self._request(
            "GET",
            f"/sap/bc/adt/functions/groups/{quote(name, safe='')}/source/main",
            accept="text/plain",
        )

        if resp.status_code == 200:
            return resp.text

        # Fallback: search for the FM to find its group URI, then read
        search_results = await self.search_objects(query=fm_name, object_type="FUNC")
        if search_results:
            uri = search_results[0].get("uri", "")
            if uri:
                source_uri = f"{uri}/source/main"
                resp2 = await self._request("GET", source_uri, accept="text/plain")
                if resp2.status_code == 200:
                    return resp2.text

        raise ADTError(
            f"Function module '{fm_name}' not found",
            status_code=404,
        )

    async def read_include_source(self, include_name: str) -> str:
        """Read ABAP include source code."""
        name = include_name.strip().lower()
        resp = await self._request(
            "GET",
            f"/sap/bc/adt/programs/includes/{quote(name, safe='')}/source/main",
            accept="text/plain",
        )

        if resp.status_code == 200:
            return resp.text
        raise ADTError(f"Include '{include_name}' not found", status_code=resp.status_code)

    async def read_function_group_source(self, group_name: str) -> str:
        """Read a function group through its generated main program when needed."""
        name = group_name.strip().lower()
        direct = await self._request(
            "GET",
            f"/sap/bc/adt/functions/groups/{quote(name, safe='')}/source/main",
            accept="text/plain",
        )
        if direct.status_code == 200:
            return direct.text

        generated_program = f"sapl{name}"
        return await self.read_program_source(generated_program)

    async def read_source_by_uri(self, object_uri: str, object_type: str = "") -> str:
        """Read source code using an exact ADT object URI from package browsing."""
        uri = object_uri.strip().split("#", 1)[0]
        if uri.startswith(self.base_url):
            uri = uri[len(self.base_url):]
        if not uri:
            raise ADTError("ADT object URI is empty")

        candidates = [uri] if "/source/" in uri else [f"{uri.rstrip('/')}/source/main"]
        for source_uri in candidates:
            resp = await self._request("GET", source_uri, accept="text/plain")
            if resp.status_code == 200:
                return resp.text

        obj_type = object_type.upper().strip()
        if obj_type == "FUGR":
            group_name = uri.rstrip("/").split("/")[-1]
            return await self.read_function_group_source(group_name)

        raise ADTError(
            f"Could not read source for ADT URI '{object_uri}'",
            status_code=404,
        )

    async def read_object_source(
        self, object_name: str, object_type: str = "PROG", object_uri: str = ""
    ) -> str:
        """
        Generic source reader — dispatches to the correct ADT path
        based on object type.
        """
        obj_type = object_type.upper().strip()
        if object_uri:
            return await self.read_source_by_uri(object_uri, obj_type)
        if obj_type in ("PROG", "REPS", "1"):
            return await self.read_program_source(object_name)
        elif obj_type in ("INCL", "PROG/I"):
            return await self.read_include_source(object_name)
        elif obj_type in ("CLAS", "INTF"):
            return await self.read_class_source(object_name)
        elif obj_type == "FUGR":
            return await self.read_function_group_source(object_name)
        elif obj_type == "FUNC":
            return await self.read_function_module_source(object_name)
        else:
            # Try program first, then class
            try:
                return await self.read_program_source(object_name)
            except ADTError:
                return await self.read_class_source(object_name)

    # ─── ATC Check ──────────────────────────────────────────────────

    async def run_atc_check(
        self, object_name: str, object_type: str = "PROG"
    ) -> List[Dict[str, Any]]:
        """
        Create and run an ATC check on an ABAP object.
        Returns a list of finding dicts.
        """
        # Map simple types to ADT object types
        adt_type_map = {
            "PROG": "PROG/P",
            "CLAS": "CLAS/OC",
            "INTF": "INTF/OI",
            "FUGR": "FUGR/F",
            "FUNC": "FUGR/FF",
        }
        adt_obj_type = adt_type_map.get(object_type.upper(), "PROG/P")

        # Step 1: Create ATC run
        run_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<atc:runparameters xmlns:atc="http://www.sap.com/adt/atc">
  <objectSets>
    <objectSet kind="inclusive">
      <adtObject adtObjectName="{object_name.upper()}"
                 adtObjectType="{adt_obj_type}"/>
    </objectSet>
  </objectSets>
</atc:runparameters>"""

        resp = await self._request(
            "POST",
            "/sap/bc/adt/atc/runs",
            headers={"Content-Type": "application/vnd.sap.atc.run.parameters.v1+xml"},
            content=run_xml,
        )

        if resp.status_code not in (200, 201):
            logger.warning("ATC run creation failed: HTTP %d", resp.status_code)
            return []

        # Step 2: Extract the worklist ID from Location header or response body
        worklist_url = resp.headers.get("location", "")
        if not worklist_url:
            # Try to parse from response body
            try:
                root = ET.fromstring(resp.text)
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag in ("worklistId", "worklist"):
                        worklist_url = elem.text or elem.get("uri", "")
                        break
            except ET.ParseError:
                pass

        if not worklist_url:
            logger.warning("Could not determine ATC worklist URL")
            return []

        # Step 3: Fetch results
        if not worklist_url.startswith("/"):
            worklist_url = f"/sap/bc/adt/atc/worklists/{worklist_url}"

        resp2 = await self._request("GET", worklist_url)
        if resp2.status_code != 200:
            logger.warning("ATC results fetch failed: HTTP %d", resp2.status_code)
            return []

        return self._parse_atc_findings(resp2.text, object_name)

    def _parse_atc_findings(
        self, xml_text: str, object_name: str
    ) -> List[Dict[str, Any]]:
        """Parse ATC worklist XML into finding dicts."""
        findings: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
            for finding_elem in root.iter():
                tag = (
                    finding_elem.tag.split("}")[-1]
                    if "}" in finding_elem.tag
                    else finding_elem.tag
                )
                if tag != "finding":
                    continue

                finding: Dict[str, Any] = {
                    "object_name": object_name,
                    "checkId": finding_elem.get("checkId", ""),
                    "checkTitle": finding_elem.get("checkTitle", ""),
                    "message": finding_elem.get("messageTitle", finding_elem.get("message", "")),
                    "priority": finding_elem.get("priority", "3"),
                    "uri": finding_elem.get("uri", ""),
                    "quickFixAvailable": finding_elem.get("quickFixAvailable", "false") == "true",
                }

                # Extract location info
                location = {}
                for child in finding_elem:
                    child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if child_tag == "location":
                        location["uri"] = child.get("uri", "")
                        # Parse line number from URI fragment
                        uri_text = child.get("uri", "")
                        line_match = re.search(r"#start=(\d+)", uri_text)
                        if line_match:
                            location["line"] = int(line_match.group(1))
                    elif child_tag == "quickfixes":
                        finding["quickFixAvailable"] = True

                finding["location"] = location
                finding["line"] = location.get("line", 0)
                finding["column"] = location.get("column", 0)

                findings.append(finding)

        except ET.ParseError:
            logger.warning("Could not parse ATC findings XML")

        return findings

    # ─── Object Info ────────────────────────────────────────────────

    async def get_object_info(
        self, object_name: str, object_type: str = "PROG"
    ) -> Dict[str, str]:
        """Get metadata about an ABAP object."""
        name = object_name.strip().lower()
        obj_type = object_type.upper()

        path_map = {
            "PROG": f"/sap/bc/adt/programs/programs/{quote(name, safe='')}",
            "CLAS": f"/sap/bc/adt/oo/classes/{quote(name, safe='')}",
            "INTF": f"/sap/bc/adt/oo/interfaces/{quote(name, safe='')}",
            "FUGR": f"/sap/bc/adt/functions/groups/{quote(name, safe='')}",
        }
        path = path_map.get(obj_type, path_map["PROG"])

        resp = await self._request("GET", path)
        if resp.status_code != 200:
            return {}

        info: Dict[str, str] = {"name": object_name, "type": obj_type}
        try:
            root = ET.fromstring(resp.text)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag == "packageRef":
                    info["package"] = elem.get(
                        "{http://www.sap.com/adt/core}name",
                        elem.get("adtcore:name", elem.get("name", "")),
                    )
                elif tag == "description":
                    info["description"] = elem.text or ""
        except ET.ParseError:
            pass

        return info

    # ─── New ATC and Package Methods ────────────────────────────────

    async def get_atc_results(self) -> List[Dict[str, Any]]:
        """Retrieve historical/central ATC check run results.
        
        Tries multiple ADT endpoints since the available API varies by
        SAP release and configuration.
        """
        # Strategy: try multiple endpoints that may expose ATC result sets
        endpoints = [
            ("/sap/bc/adt/atc/results?activeResult=true", "application/xml"),
            ("/sap/bc/adt/atc/results?activeResult=true", "application/atc.worklist.v1+xml"),
            ("/sap/bc/adt/atc/results?activeResult=true", "application/atom+xml"),
            ("/sap/bc/adt/atc/worklists", "application/xml"),
            ("/sap/bc/adt/atc/worklists", "application/atc.worklist.v1+xml"),
            ("/sap/bc/adt/atc/worklists", "application/atom+xml"),
            ("/sap/bc/adt/atc/runs", "application/xml"),
            ("/sap/bc/adt/atc/runs", "application/atom+xml"),
            ("/sap/bc/adt/atc/results", "application/xml"),
        ]
        
        last_error = ""
        for path, accept in endpoints:
            try:
                resp = await self._request("GET", path, accept=accept)
                logger.debug(
                    "ATC results probe %s (Accept: %s) → HTTP %d, body[:500]=%s",
                    path, accept, resp.status_code, resp.text[:500] if resp.text else "(empty)",
                )
                if resp.status_code == 200 and resp.text.strip():
                    results = self._parse_atc_results_xml(resp.text)
                    if results:
                        logger.info(
                            "ATC results fetched via %s (%s): %d result(s)",
                            path, accept, len(results),
                        )
                        return results
                elif resp.status_code not in (400, 404, 405, 406, 501):
                    last_error = f"{path} returned HTTP {resp.status_code}"
            except Exception as exc:
                last_error = f"{path} failed: {exc}"
                logger.debug("ATC results probe %s failed: %s", path, exc)
        
        if last_error:
            logger.warning("All ATC result endpoints failed. Last error: %s", last_error)
        return []

    def _parse_atc_results_xml(self, xml_text: str) -> List[Dict[str, Any]]:
        """Parse ATC results/worklists XML from multiple possible formats."""
        results: List[Dict[str, Any]] = []
        seen_ids: set = set()
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning("Could not parse ATC results XML")
            return results

        # Walk every element looking for result/entry/worklist/run nodes or display IDs
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            result_id = (
                elem.get("id") or elem.get("worklistId")
                or elem.get("displayId")
                or elem.get("{http://www.sap.com/adt/atc}id")
                or ""
            )
            title = elem.get("title") or elem.get("name") or ""
            timestamp_str = (
                elem.get("timestamp") or elem.get("createdAt")
                or elem.get("changedAt") or elem.get("updated") or ""
            )
            object_set = elem.get("objectSet") or elem.get("objectSetName") or ""
            findings_count_str = elem.get("findingCount") or elem.get("numberOfFindings") or "0"

            # Check child elements of this element (handling nested/activeResult structures)
            for child in elem:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                ctext = (child.text or "").strip()
                if ctag == "displayId" and ctext:
                    result_id = ctext
                elif ctag == "worklistId" and ctext:
                    result_id = ctext
                elif ctag == "id" and ctext and not result_id:
                    result_id = ctext
                elif ctag == "title" and ctext:
                    title = ctext
                elif ctag == "runSeries" and ctext:
                    title = f"ATC Series: {ctext}"
                    object_set = ctext
                elif ctag == "timestamp" and ctext:
                    timestamp_str = ctext
                elif ctag == "createdAt" and ctext:
                    timestamp_str = ctext
                elif ctag in ("findingCount", "findingsCount", "numberOfFindings") and ctext:
                    findings_count_str = ctext
                elif ctag == "aggregates":
                    for inner_child in child:
                        ictag = inner_child.tag.split("}")[-1] if "}" in inner_child.tag else inner_child.tag
                        ictext = (inner_child.text or "").strip()
                        if ictag in ("findingCount", "findingsCount", "numberOfFindings") and ictext:
                            findings_count_str = ictext

            # For Atom <entry> format, look in child elements
            if tag == "entry":
                for child in elem:
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    ctext = (child.text or "").strip()
                    if ctag == "id" and not result_id:
                        result_id = ctext.replace("urn:uuid:", "").replace("uuid:", "")
                    elif ctag == "title" and not title:
                        title = ctext
                    elif ctag == "updated" and not timestamp_str:
                        timestamp_str = ctext
                    elif ctag == "published" and not timestamp_str:
                        timestamp_str = ctext
                    elif ctag == "content":
                        # Drill into <content> for nested result info
                        for inner in child:
                            itag = inner.tag.split("}")[-1] if "}" in inner.tag else inner.tag
                            if itag in ("resultInfo", "worklist", "run", "result"):
                                if not result_id:
                                    result_id = inner.get("id") or inner.get("worklistId") or inner.get("displayId") or ""
                                if not title:
                                    title = inner.get("title") or inner.get("name") or ""
                                if not object_set:
                                    object_set = inner.get("objectSet") or inner.get("objectSetName") or ""
                                if not findings_count_str or findings_count_str == "0":
                                    findings_count_str = inner.get("findingCount") or inner.get("numberOfFindings") or findings_count_str
                    elif ctag == "link":
                        href = child.get("href", "")
                        if not result_id and "/atc/worklists/" in href:
                            result_id = href.split("/atc/worklists/")[-1].split("?")[0]

            # Also check for direct children that hold the ID
            if not result_id:
                for child in elem:
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag in ("id", "worklistId", "runId", "displayId"):
                        result_id = (child.text or "").strip().replace("urn:uuid:", "").replace("uuid:", "")
                        break

            if not result_id:
                continue

            result_id = result_id.replace("urn:uuid:", "").replace("uuid:", "")
            if result_id in seen_ids:
                continue

            # Skip adding nested child leaf tags as elements themselves
            if tag in ("displayId", "worklistId", "id", "title", "timestamp", "createdAt", "findingCount", "findingsCount", "numberOfFindings", "aggregates"):
                continue

            seen_ids.add(result_id)

            # Parse timestamp
            timestamp = None
            if timestamp_str:
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y%m%d%H%M%S"):
                    try:
                        clean = timestamp_str.replace("+00:00", "").replace("Z", "")
                        if "." in clean:
                            clean = clean.split(".")[0]
                        timestamp = datetime.strptime(clean, fmt)
                        break
                    except ValueError:
                        continue
                if not timestamp:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    except Exception:
                        pass
            if not timestamp:
                timestamp = datetime.utcnow()

            # Parse findings count
            try:
                fc = int(findings_count_str)
            except (ValueError, TypeError):
                fc = 0

            results.append({
                "id": result_id,
                "title": title or f"ATC Run {result_id[:8]}",
                "timestamp": timestamp,
                "object_set": object_set,
                "findings_count": fc,
            })

        return results

    async def get_atc_worklist_findings(self, result_id: str) -> List[Dict[str, Any]]:
        """Fetch all findings for a specific ATC worklist/result ID."""
        import uuid
        clean_id = result_id.strip()
        is_central_display = len(clean_id) == 32 and "-" not in clean_id

        target_id = clean_id
        if is_central_display:
            session_uuid = str(uuid.uuid4())
            logger.info("Associating central result display ID %s with new worklist session %s via PUT", clean_id, session_uuid)
            assoc_path = f"/sap/bc/adt/atc/result/worklist/{session_uuid}/{clean_id}"
            try:
                # Use application/atc.worklist.v1+xml Accept header for association
                put_resp = await self._request("PUT", assoc_path, accept="application/atc.worklist.v1+xml")
                logger.debug("PUT association response: HTTP %d", put_resp.status_code)
                if put_resp.status_code in (200, 201, 204):
                    target_id = session_uuid
                else:
                    logger.warning("Association failed (status %d), attempting direct get", put_resp.status_code)
            except Exception as e:
                logger.error("Exception during PUT association: %s", e)

        accept_headers = [
            "application/atc.worklist.v1+xml",
            "application/vnd.sap.atc.worklist.v1+xml",
            "application/xml",
            "application/atom+xml",
        ]
        
        resp = None
        for accept in accept_headers:
            resp = await self._request(
                "GET",
                f"/sap/bc/adt/atc/worklists/{target_id}",
                accept=accept,
            )
            if resp.status_code == 200 and resp.text.strip():
                logger.debug("ATC worklist %s fetched with Accept: %s", target_id, accept)
                break
            logger.debug(
                "ATC worklist %s with Accept %s → HTTP %d",
                target_id, accept, resp.status_code,
            )
        
        if not resp or resp.status_code != 200:
            status = resp.status_code if resp else 0
            logger.warning("Failed to fetch ATC worklist findings for %s: HTTP %d", target_id, status)
            return []

        findings = []
        try:
            root = ET.fromstring(resp.text)
            
            def _get_attr(elem, local_name):
                for ns in ("", "{http://www.sap.com/adt/atc/finding}", "{http://www.sap.com/adt/core}", "{http://www.sap.com/adt/atc}"):
                    val = elem.get(f"{ns}{local_name}")
                    if val is not None:
                        return val
                return None

            for obj_elem in root.iter():
                obj_tag = obj_elem.tag.split("}")[-1] if "}" in obj_elem.tag else obj_elem.tag
                if obj_tag != "object":
                    continue
                
                obj_name = obj_elem.get("name") or obj_elem.get("{http://www.sap.com/adt/core}name") or ""
                obj_type_raw = obj_elem.get("type") or obj_elem.get("{http://www.sap.com/adt/core}type") or ""
                obj_type = obj_type_raw.split("/")[0] if obj_type_raw else "PROG"
                package_name = obj_elem.get("packageName") or ""
                
                for finding_elem in obj_elem.iter():
                    find_tag = finding_elem.tag.split("}")[-1] if "}" in finding_elem.tag else finding_elem.tag
                    if find_tag != "finding":
                        continue
                    
                    check_id = _get_attr(finding_elem, "checkId") or ""
                    check_title = _get_attr(finding_elem, "checkTitle") or ""
                    message = _get_attr(finding_elem, "messageTitle") or _get_attr(finding_elem, "message") or ""
                    priority = _get_attr(finding_elem, "priority") or "3"
                    uri = _get_attr(finding_elem, "uri") or ""
                    location_uri = _get_attr(finding_elem, "location") or ""
                    quick_fix_info = _get_attr(finding_elem, "quickfixInfo") or _get_attr(finding_elem, "quickFixAvailable")
                    
                    finding = {
                        "object_name": obj_name,
                        "object_type": obj_type,
                        "package_name": package_name,
                        "checkId": check_id,
                        "checkTitle": check_title,
                        "message": message,
                        "priority": priority,
                        "uri": uri,
                        "quickFixAvailable": bool(quick_fix_info) or (quick_fix_info == "true"),
                    }
                    
                    # Parse location
                    line_num = 0
                    if location_uri:
                        line_match = re.search(r"#start=(\d+)", location_uri)
                        if line_match:
                            line_num = int(line_match.group(1))
                            
                    location = {"uri": location_uri, "line": line_num}
                    
                    # Fallback to children elements if needed
                    for child in finding_elem:
                        child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if child_tag == "location":
                            location["uri"] = child.get("uri", location_uri)
                            uri_text = child.get("uri", "")
                            line_match = re.search(r"#start=(\d+)", uri_text)
                            if line_match:
                                location["line"] = int(line_match.group(1))
                        elif child_tag == "quickfixes":
                            finding["quickFixAvailable"] = True
                            
                    finding["location"] = location
                    finding["line"] = location.get("line", 0)
                    finding["column"] = location.get("column", 0)
                    findings.append(finding)
        except ET.ParseError:
            logger.warning("Could not parse ATC worklist XML")
            
        return findings

    async def run_atc_on_package(self, package_name: str) -> Dict[str, Any]:
        """Trigger a fresh ATC check on an entire package and return the worklist ID."""
        package = package_name.strip().upper()
        run_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<atc:runparameters xmlns:atc="http://www.sap.com/adt/atc">
  <objectSets>
    <objectSet kind="inclusive">
      <adtObject adtObjectName="{package}"
                 adtObjectType="DEVC/K"/>
    </objectSet>
  </objectSets>
</atc:runparameters>"""

        resp = await self._request(
            "POST",
            "/sap/bc/adt/atc/runs",
            headers={"Content-Type": "application/vnd.sap.atc.run.parameters.v1+xml"},
            content=run_xml,
        )

        if resp.status_code not in (200, 201):
            raise ADTError(
                f"ATC run on package {package} failed: HTTP {resp.status_code}",
                status_code=resp.status_code,
                detail=resp.text[:500],
            )

        # Extract worklist ID from Location header or response body
        worklist_id = resp.headers.get("location", "")
        if not worklist_id:
            try:
                root = ET.fromstring(resp.text)
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag in ("worklistId", "worklist", "id"):
                        worklist_id = (elem.text or elem.get("uri", "")).strip()
                        break
            except ET.ParseError:
                pass

        if not worklist_id:
            raise ADTError("ATC run succeeded but could not determine worklist ID")

        # Normalize: if it's a full path, extract just the ID
        if "/" in worklist_id:
            worklist_id = worklist_id.rstrip("/").split("/")[-1]

        return {"worklist_id": worklist_id, "package": package}


    def _parse_package_tree(self, xml_text: str, package_name: str) -> List[Dict[str, Any]]:
        """Parse ADT package tree asXML into exact package object entries."""
        objects: List[Dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        try:
            root = ET.fromstring(xml_text)
            for node in root.iter():
                tag = node.tag.split("}")[-1] if "}" in node.tag else node.tag
                if tag != "SEU_ADT_REPOSITORY_OBJ_NODE":
                    continue

                values: Dict[str, str] = {}
                for child in node:
                    child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    values[child_tag] = (child.text or "").strip()

                adt_type = values.get("OBJECT_TYPE", "").upper()
                if not adt_type or adt_type.startswith("DEVC/"):
                    continue

                name = values.get("OBJECT_NAME") or values.get("TECH_NAME")
                if not name:
                    continue

                uri = values.get("OBJECT_URI", "")
                simple_type = _simple_object_type(adt_type)
                if simple_type and simple_type not in SOURCE_SUPPORTED_OBJECT_TYPES:
                    continue

                key = (name.upper(), simple_type, uri)
                if key in seen:
                    continue
                seen.add(key)

                objects.append({
                    "name": name,
                    "type": simple_type,
                    "package": package_name.strip().upper(),
                    "uri": uri,
                    "adt_type": adt_type,
                    "description": values.get("DESCRIPTION", ""),
                    "source_supported": _source_supported(adt_type),
                })
        except ET.ParseError:
            logger.warning("Could not parse ADT package tree XML")
        return objects

    async def get_objects_by_package(self, package_name: str, max_results: int = 5000) -> List[Dict[str, Any]]:
        """List exact repository objects in a package."""
        package = package_name.strip().upper()
        resp = await self._request(
            "POST",
            "/sap/bc/adt/repository/nodestructure",
            params={"parent_name": package, "parent_type": "DEVC/K"},
            headers={"Content-Type": "application/vnd.sap.as+xml"},
            accept="application/vnd.sap.as+xml",
            timeout=120.0,
        )
        if resp.status_code == 200 and resp.text.strip():
            objects = self._parse_package_tree(resp.text, package)
            if objects:
                return objects

        logger.warning(
            "ADT package tree for %s returned HTTP %d with %d bytes; trying strict search fallback",
            package,
            resp.status_code,
            len(resp.text),
        )

        params: Dict[str, str] = {
            "operation": "quickSearch",
            "query": "*",
            "package": package,
            "maxResults": str(max_results),
        }
        resp = await self._request(
            "GET",
            "/sap/bc/adt/repository/informationsystem/search",
            params=params,
            timeout=120.0,
        )
        if resp.status_code != 200:
            logger.warning("Search by package %s failed: HTTP %d", package_name, resp.status_code)
            return []

        objects = []
        for obj in self._parse_search_results(resp.text):
            adt_type = obj.get("type", "").upper()
            obj_package = obj.get("package", "").upper()
            if obj_package and obj_package != package:
                continue
            if adt_type.startswith("DEVC/"):
                continue
            if not _source_supported(adt_type):
                continue
            objects.append({
                **obj,
                "type": _simple_object_type(adt_type),
                "adt_type": adt_type,
                "source_supported": True,
            })
        return objects
