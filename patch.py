content = open('backend/services/schema_discovery.py').read()
old = 'tables = await db_manager.list_tables(connection_id, schema)'
new = 'tables = await db_manager.list_tables(connection_id)'
print('found:', old in content)
content = content.replace(old, new)
open('backend/services/schema_discovery.py', 'w').write(content)
print('done')