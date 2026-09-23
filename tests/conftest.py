import os
from pathlib import Path

TEST_DB = Path('/tmp/mom_travel_desk_test.db')
if TEST_DB.exists(): TEST_DB.unlink()
os.environ['TRAVEL_DESK_DB'] = str(TEST_DB)
os.environ['OPENCLAW_ENABLED'] = 'false'
