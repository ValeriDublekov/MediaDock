import email.utils
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
import xml.etree.ElementTree as ET

class SimpleFeedParserDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            return None

class SimpleFeedParser:
    @staticmethod
    def parse(content):
        import os
        if isinstance(content, str):
            if os.path.exists(content):
                with open(content, "rb") as f:
                    xml_bytes = f.read()
            else:
                xml_bytes = content.encode("utf-8")
        else:
            xml_bytes = content

        entries = []
        bozo = False
        bozo_exception = None
        try:
            root = ET.fromstring(xml_bytes)
            # Support RSS 2.0
            for item in root.findall(".//item"):
                title_elem = item.find("title")
                link_elem = item.find("link")
                guid_elem = item.find("guid")
                pub_date_elem = item.find("pubDate")
                pub_str = pub_date_elem.text if pub_date_elem is not None else ""
                parsed_time = None
                if pub_str:
                    try:
                        parsed_tuple = email.utils.parsedate_tz(pub_str)
                        if parsed_tuple:
                            parsed_time = parsed_tuple[:9]
                    except Exception:
                        pass
                entry = SimpleFeedParserDict({
                    "title": title_elem.text if title_elem is not None else "",
                    "link": link_elem.text if link_elem is not None else "",
                    "id": guid_elem.text if guid_elem is not None else (link_elem.text if link_elem is not None else ""),
                    "published": pub_str,
                    "published_parsed": parsed_time,
                })
                entries.append(entry)
            
            # Support Atom
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry_elem in root.findall(".//atom:entry", ns) or root.findall(".//entry"):
                title_elem = entry_elem.find("atom:title", ns) if entry_elem.find("atom:title", ns) is not None else entry_elem.find("title")
                link_elem = entry_elem.find("atom:link", ns) if entry_elem.find("atom:link", ns) is not None else entry_elem.find("link")
                id_elem = entry_elem.find("atom:id", ns) if entry_elem.find("atom:id", ns) is not None else entry_elem.find("id")
                updated_elem = entry_elem.find("atom:updated", ns) if entry_elem.find("atom:updated", ns) is not None else entry_elem.find("updated")
                
                link_href = ""
                if link_elem is not None:
                    link_href = link_elem.attrib.get("href", link_elem.text or "")
                pub_str = updated_elem.text if updated_elem is not None else ""
                parsed_time = None
                if pub_str:
                    try:
                        import datetime
                        dt = datetime.datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                        parsed_time = dt.utctimetuple()
                    except Exception:
                        pass
                
                entry = SimpleFeedParserDict({
                    "title": title_elem.text if title_elem is not None else "",
                    "link": link_href,
                    "id": id_elem.text if id_elem is not None else link_href,
                    "published": pub_str,
                    "published_parsed": parsed_time,
                })
                entries.append(entry)
        except Exception as exc:
            bozo = True
            bozo_exception = exc

        return SimpleFeedParserDict({
            "entries": entries,
            "bozo": 1 if bozo else 0,
            "bozo_exception": bozo_exception,
            "feed": SimpleFeedParserDict({"title": "Feed"}),
        })

class RequestException(IOError):
    pass

class Timeout(RequestException):
    pass

class ConnectionError(RequestException):
    pass

class HTTPError(RequestException):
    pass

class TooManyRedirects(RequestException):
    pass

# Stubs for third-party dependencies if not installed in current environment
for mod_name in [
    "requests",
    "requests.exceptions",
    "feedparser",
    "firebase_admin",
    "firebase_admin.credentials",
    "firebase_admin.firestore",
    "google",
    "google.cloud",
    "google.cloud.firestore",
    "google.cloud.firestore_v1",
    "google.cloud.firestore_v1.field_path",
    "google.genai",
    "google.genai.types",
    "google.genai.errors",
]:
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except ImportError:
            if mod_name == "feedparser":
                sys.modules[mod_name] = SimpleFeedParser()
            elif mod_name == "requests":
                req_mock = MagicMock()
                req_mock.exceptions = SimpleNamespace(
                    RequestException=RequestException,
                    Timeout=Timeout,
                    ConnectionError=ConnectionError,
                    HTTPError=HTTPError,
                    TooManyRedirects=TooManyRedirects,
                )
                req_mock.RequestException = RequestException
                req_mock.Timeout = Timeout
                req_mock.ConnectionError = ConnectionError
                req_mock.HTTPError = HTTPError
                req_mock.TooManyRedirects = TooManyRedirects
                sys.modules[mod_name] = req_mock
            elif mod_name == "requests.exceptions":
                sys.modules[mod_name] = SimpleNamespace(
                    RequestException=RequestException,
                    Timeout=Timeout,
                    ConnectionError=ConnectionError,
                    HTTPError=HTTPError,
                    TooManyRedirects=TooManyRedirects,
                )
            else:
                stub = MagicMock()
                sys.modules[mod_name] = stub
