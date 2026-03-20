from pydantic import BaseModel
from typing import Optional


class CarItem(BaseModel):
    body_type: Optional[str] = None
    
    brand: str
    model: str
    year: int
    price: int
    city: str

    spec: Optional[str] = None

    is_active: bool
    has_issues: bool
    needs_repair: bool
    is_owner: bool

    eng_vol: Optional[float] = None
    eng_hp: Optional[int] = None
    fuel: Optional[str] = None
    gearbox: Optional[str] = None
    drive: Optional[str] = None
    mileage: int = 0

    img_url: Optional[str] = None

    url: str

    parse_date: str
    posted_date: Optional[str] = None