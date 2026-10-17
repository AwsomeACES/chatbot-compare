from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class Message(BaseModel):
    message: str


@app.post("/chat")
def chat(x: Message):
    return {"answer": "Hello " + x.message}
