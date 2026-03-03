"""
Input validation utilities.
"""

import re
import os
import ipaddress
from typing import Optional, Tuple


# ==========================================================
# CONNECTION VALIDATION
# ==========================================================

def validate_connection_config(
    host: str,
    port: int,
    database: str,
    username: str,
) -> Tuple[bool, Optional[str]]:
    """
    Validate database connection configuration.
    """

    if not host or not host.strip():
        return False, "Host cannot be empty"

    if not database or not database.strip():
        return False, "Database name cannot be empty"

    if not username or not username.strip():
        return False, "Username cannot be empty"

    if not isinstance(port, int) or port < 1 or port > 65535:
        return False, "Port must be between 1 and 65535"

    host = host.strip()

    # Validate IP address (IPv4 / IPv6)
    try:
        ipaddress.ip_address(host)
        return True, None
    except ValueError:
        pass

    # Validate domain name or localhost
    domain_pattern = r"^(localhost|[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+)$"
    if not re.match(domain_pattern, host):
        return False, "Invalid host format"

    return True, None


# ==========================================================
# NATURAL LANGUAGE QUERY VALIDATION
# ==========================================================

def validate_natural_language_query(query: str) -> Tuple[bool, Optional[str]]:
    """
    Validate natural language query input.
    """

    if not query or not query.strip():
        return False, "Query cannot be empty"

    query = query.strip()

    if len(query) < 3:
        return False, "Query too short (minimum 3 characters)"

    if len(query) > 5000:
        return False, "Query too long (max 5000 characters)"

    return True, None


# ==========================================================
# FILENAME VALIDATION
# ==========================================================

def validate_sql_filename(filename: str) -> Tuple[bool, Optional[str]]:
    """
    Validate filename for SQL export.
    """

    if not filename or not filename.strip():
        return False, "Filename cannot be empty"

    filename = filename.strip()

    # Prevent hidden files
    if filename.startswith("."):
        return False, "Filename cannot start with a dot"

    if len(filename) > 255:
        return False, "Filename too long"

    # Allow only safe characters
    if not re.match(r"^[a-zA-Z0-9_.-]+$", filename):
        return False, "Filename contains invalid characters"

    # Validate extension
    name, ext = os.path.splitext(filename.lower())
    dangerous_extensions = {".exe", ".bat", ".sh", ".cmd", ".ps1"}

    if ext in dangerous_extensions:
        return False, "Forbidden file extension"

    return True, None


# ==========================================================
# INPUT SANITIZER
# ==========================================================

def sanitize_input(text: str, max_length: int = 1000) -> str:
    """
    Sanitize user input safely.
    """

    if not text:
        return ""

    # Trim whitespace
    text = text.strip()

    # Truncate safely
    if len(text) > max_length:
        text = text[:max_length]

    # Remove control characters
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Normalize multiple spaces
    text = re.sub(r"\s+", " ", text)

    return text