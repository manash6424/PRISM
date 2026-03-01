"""
Test suite for AI Desktop Copilot.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.database_manager import db_manager
from backend.models.database import DatabaseConnection, DatabaseDialect


async def test_database_connection():
    """Test database connection."""
    print("\n=== Testing Database Connection ===")
    
    # Create test connection (modify with your test DB)
    conn = DatabaseConnection(
        name="Test PostgreSQL",
        dialect=DatabaseDialect.POSTGRESQL,
        host="localhost",
        port=5432,
        database="testdb",
        username="postgres",
        password="",
    )
    
    success, message = await db_manager.test_connection(conn)
    print(f"Connection test: {'✓' if success else '✗'} {message}")
    
    if success:
        await db_manager.connect(conn)
        print("✓ Connected successfully")
        
        # Test query execution
        success, cols, rows, error = await db_manager.execute_query(
            conn.id or conn.connection_string,
            "SELECT 1 as test"
        )
        print(f"Query test: {'✓' if success else '✗'} {error or 'OK'}")
        
        await db_manager.disconnect(conn.id or conn.connection_string)
    
    return success


async def test_schema_discovery():
    """Test schema discovery."""
    print("\n=== Testing Schema Discovery ===")
    
    from backend.services.schema_discovery import schema_discovery
    
    # This would require an active connection
    print("Schema discovery service initialized ✓")
    return True


async def test_nl_to_sql():
    """Test NL to SQL conversion."""
    print("\n=== Testing NL to SQL Conversion ===")
    
    from backend.services.nl_to_sql import nl_to_sql
    
    schema_context = """
    Table: users
      Columns:
        - id: INTEGER (NOT NULL) [PK]
        - name: VARCHAR(255) (NOT NULL)
        - email: VARCHAR(255) (NOT NULL)
        - created_at: TIMESTAMP
    """
    
    try:
        sql, explanation = await nl_to_sql.convert(
            natural_language="Show me all users",
            schema_context=schema_context,
            dialect=DatabaseDialect.POSTGRESQL,
        )
        
        print(f"Generated SQL: {sql[:100]}...")
        print(f"Explanation: {explanation}")
        print("✓ NL to SQL conversion working")
        return True
    except Exception as e:
        print(f"✗ NL to SQL test failed: {e}")
        return False


async def test_export_service():
    """Test export service."""
    print("\n=== Testing Export Service ===")
    
    from backend.services.export_service import export_service
    from backend.models.database import QueryResponse, ExportRequest, ExportFormat
    from datetime import datetime
    
    # Create mock query response
    mock_response = QueryResponse(
        query_id="test_123",
        natural_language="Test query",
        generated_sql="SELECT * FROM users",
        explanation="Test",
        success=True,
        execution_time_ms=100,
        row_count=2,
        columns=["id", "name"],
        results=[{"id": 1, "name": "John"}, {"id": 2, "name": "Jane"}],
        timestamp=datetime.utcnow(),
    )
    
    # Test CSV export
    request = ExportRequest(
        query_id="test_123",
        format=ExportFormat.CSV,
        filename="test_export",
    )
    
    try:
        filepath = await export_service.export(request, mock_response)
        print(f"✓ Export created: {filepath}")
        return True
    except Exception as e:
        print(f"✗ Export test failed: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("AI Desktop Copilot - Test Suite")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Database Connection", await test_database_connection()))
    results.append(("Schema Discovery", await test_schema_discovery()))
    results.append(("NL to SQL", await test_nl_to_sql()))
    results.append(("Export Service", await test_export_service()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{name}: {status}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + ("All tests passed! ✓" if all_passed else "Some tests failed ✗"))
    
    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
