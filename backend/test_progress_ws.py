import asyncio, websockets, json

async def main():
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZDdkZTE4NC00ZTE5LTRmMzktOWE0My02NjNhNDE1ZmIxZmIiLCJyb2xlIjoidXNlciIsInR5cGUiOiJhY2Nlc3MiLCJpYXQiOjE3ODcwNDczMDgsImV4cCI6MTc4NzEzMzcwOH0.SXU2rdEy4BcrGj1Z-98O-tRjhzwusQLiMvdeWhfB4IU"
    tender_id = "0d42f029-4ec9-4248-bb9c-1d3f47061083"
    uri = f"ws://127.0.0.1:8000/ws/tenders/{tender_id}/progress?token={token}"
    async with websockets.connect(uri) as ws:
        msg = await ws.recv()
        data = json.loads(msg)
        print(json.dumps(data, indent=2))

asyncio.run(main())