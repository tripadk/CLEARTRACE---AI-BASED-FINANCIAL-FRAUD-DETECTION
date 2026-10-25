from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TransactionIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=100)
    timestamp: datetime | None = None
    simulation_step: int | None = Field(default=None, ge=0)
    sender: str = Field(min_length=1, max_length=100)
    receiver: str = Field(min_length=1, max_length=100)
    amount: float = Field(ge=0)
    currency: str = "USD"
    channel: str = "wire"
    description: str = ""

    @model_validator(mode="after")
    def require_one_time_representation(self):
        if (self.timestamp is None) == (self.simulation_step is None):
            raise ValueError("Provide exactly one of timestamp or simulation_step.")
        return self


class TransactionOut(TransactionIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_score: float
    graph_score: float
    temporal_score: float
    anomaly_score: float
    risk_score: float
    reasons: list[str]
    review_status: str
