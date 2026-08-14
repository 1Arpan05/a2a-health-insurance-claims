from dataclasses import dataclass
from datetime import datetime
import uuid

@dataclass
class Message:
    sender:str
    receiver:str
    task:str
    message:str
    status:str="pending"
    id:str=""
    timestamp:str=""

    def __post_init__(self):
        self.id = str(uuid.uuid4())
        self.timestamp = str(datetime.now())


