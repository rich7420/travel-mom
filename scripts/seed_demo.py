from datetime import date, timedelta
from app.db import init_db
from app.models import TripCaseCreate
from app.repositories import case_repo

init_db()
if not case_repo.list():
    case_repo.create(TripCaseCreate(customer_name="陳小姐", destination="大阪", depart_date=date.today()+timedelta(days=6), return_date=date.today()+timedelta(days=10), adults=2, budget_twd=80000, notes="早去晚回、希望住難波附近"))
    case_repo.create(TripCaseCreate(customer_name="林先生一家", destination="北海道", depart_date=date.today()+timedelta(days=21), return_date=date.today()+timedelta(days=27), adults=2, children=2, notes="親子、步調不要太趕"))
print("seeded")
