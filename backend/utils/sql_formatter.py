"""
SQL formatting and validation utilities.
"""

import re
from typing import Optional, Tuple


# ==========================================================
# SQL FORMATTER
# ==========================================================

def format_sql(sql: str, dialect: str = "postgresql") -> str:
    """
    Format SQL query for readability.
    """

    if not sql or not sql.strip():
        return ""

    sql = sql.strip()

    # ✅ Strip markdown code blocks (```sql ... ``` or ``` ... ```)
    sql = re.sub(r"```(?:sql|SQL)?\s*", "", sql)
    sql = re.sub(r"```", "", sql)
    sql = sql.strip()

    # --- Uppercase important SQL keywords ---
    keywords = [
        "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "LIKE",
        "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS",
        "ON", "AS", "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET",
        "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "CREATE",
        "TABLE", "ALTER", "DROP", "INDEX", "PRIMARY", "KEY", "FOREIGN",
        "REFERENCES", "NULL", "DEFAULT", "UNIQUE", "CHECK", "CONSTRAINT",
        "UNION", "ALL", "EXCEPT", "INTERSECT", "CASE", "WHEN", "THEN",
        "ELSE", "END", "ASC", "DESC", "DISTINCT", "COUNT", "SUM", "AVG",
        "MIN", "MAX", "COALESCE", "IFNULL", "TRUE", "FALSE", "RETURNING",
        "WITH", "SHOW", "DESCRIBE", "EXPLAIN"
    ]

    for keyword in keywords:
        sql = re.sub(
            rf"\b{keyword}\b",
            keyword,
            sql,
            flags=re.IGNORECASE
        )

    # --- Add newlines before major clauses ---
    newline_keywords = [
        "SELECT", "FROM", "WHERE", "GROUP BY",
        "HAVING", "ORDER BY", "LIMIT", "OFFSET",
        "JOIN", "LEFT JOIN", "RIGHT JOIN",
        "INNER JOIN", "OUTER JOIN"
    ]

    for keyword in newline_keywords:
        pattern = rf"\b{keyword}\b"
        sql = re.sub(pattern, f"\n{keyword}", sql, flags=re.IGNORECASE)

    # --- Clean whitespace ---
    sql = re.sub(r"\n\s*\n", "\n", sql)
    sql = re.sub(r"[ \t]+", " ", sql)

    return sql.strip()


# ==========================================================
# SQL VALIDATOR
# ==========================================================

def validate_sql(sql: str) -> Tuple[bool, Optional[str]]:
    """
    Basic SQL validation.
    """

    if not sql or not sql.strip():
        return False, "Empty SQL query"

    sql_clean = sql.strip()

    # --- Block dangerous operations ---
    dangerous_patterns = [
        r"\bDROP\b",
        r"\bTRUNCATE\b",
        r"\bDELETE\s+FROM\b",
        r"\bALTER\s+TABLE\b",
        r"\bUPDATE\b",
        r"\bINSERT\s+INTO\b"
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, sql_clean, re.IGNORECASE):
            return False, "Dangerous operation not allowed"

    # --- Allow only read-only queries ---
    if not re.match(r"^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b", sql_clean, re.IGNORECASE):
        return False, "Only SELECT, WITH, SHOW, DESCRIBE, EXPLAIN queries allowed"

    return True, None


# ==========================================================
# SQL EXPLANATION GENERATOR
# ==========================================================

def generate_explanation(sql: str, dialect: str = "postgresql") -> str:
    """
    Generate human-readable explanation of SQL query.
    """

    if not sql:
        return "Empty query."

    sql_upper = sql.upper()
    explanations = []

    if re.search(r"\bSELECT\b", sql_upper):
        explanations.append("This is a SELECT query that retrieves data from the database.")

        if re.search(r"\bCOUNT\b", sql_upper):
            explanations.append("It counts matching records.")
        if re.search(r"\bSUM\b", sql_upper):
            explanations.append("It calculates the sum of a numeric column.")
        if re.search(r"\bAVG\b", sql_upper):
            explanations.append("It calculates the average of a numeric column.")
        if re.search(r"\bDISTINCT\b", sql_upper):
            explanations.append("It removes duplicate results.")

    if re.search(r"\bLEFT\s+JOIN\b", sql_upper):
        explanations.append("Uses LEFT JOIN to include all rows from the left table.")
    elif re.search(r"\bRIGHT\s+JOIN\b", sql_upper):
        explanations.append("Uses RIGHT JOIN to include all rows from the right table.")
    elif re.search(r"\bINNER\s+JOIN\b", sql_upper):
        explanations.append("Uses INNER JOIN to return matching rows only.")
    elif re.search(r"\bJOIN\b", sql_upper):
        explanations.append("Combines rows from multiple tables.")

    if re.search(r"\bWHERE\b", sql_upper):
        explanations.append("Filters results based on specified conditions.")

    if re.search(r"\bGROUP\s+BY\b", sql_upper):
        explanations.append("Groups results by specific columns.")
        if re.search(r"\bHAVING\b", sql_upper):
            explanations.append("Applies conditions to grouped results.")

    if re.search(r"\bORDER\s+BY\b", sql_upper):
        if re.search(r"\bDESC\b", sql_upper):
            explanations.append("Results are sorted in descending order.")
        else:
            explanations.append("Results are sorted in ascending order.")

    limit_match = re.search(r"\bLIMIT\s+(\d+)", sql_upper)
    if limit_match:
        explanations.append(f"Limits results to {limit_match.group(1)} rows.")

    return " ".join(explanations) if explanations else "Standard read-only database query."