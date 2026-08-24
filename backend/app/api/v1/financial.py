from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from app.deps import get_session
from app.schemas import FinancialAnalyticsResponse
from app.services.financial import FinancialService

router = APIRouter()


@router.get("/financial/contracts", response_model=FinancialAnalyticsResponse)
def get_financial_analytics(
    session: Session = Depends(get_session),
):
    """
    Returns NBA salary cap analysis, franchise payrolls, top supermax contracts,
    and highest surplus-value bargain contracts ($/PTS, $/WS, Cap Space).
    """
    service = FinancialService(session)
    try:
        return service.get_financial_analytics()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
