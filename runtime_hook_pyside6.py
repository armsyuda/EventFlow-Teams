"""Ensure frozen PySide6 extension modules can load Qt DLLs from PySide6."""

import os
import sys


if sys.platform.startswith("win") and hasattr(sys, "_MEIPASS"):
    os.add_dll_directory(os.path.join(sys._MEIPASS, "PySide6"))
    certificate_bundle = os.path.join(sys._MEIPASS, "certifi", "cacert.pem")
    if os.path.isfile(certificate_bundle):
        # Do not inherit a stale developer or corporate environment path such
        # as REQUESTS_CA_BUNDLE=C:\\Users\\...\\cacert.pem.  Requests and
        # urllib must use the certificate bundle packaged with this app.
        os.environ["REQUESTS_CA_BUNDLE"] = certificate_bundle
        os.environ["CURL_CA_BUNDLE"] = certificate_bundle
        os.environ["SSL_CERT_FILE"] = certificate_bundle
