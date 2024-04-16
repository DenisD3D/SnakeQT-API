import os
import zipfile
from xml.etree import ElementTree

import databases
import dotenv
import sqlalchemy
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, FileResponse, JSONResponse, Response

dotenv.load_dotenv()

database = databases.Database(os.environ.get("DATABASE_URL"), min_size=3, max_size=5)
metadata = sqlalchemy.MetaData()

highscores = sqlalchemy.Table(
    "highscores",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("map", sqlalchemy.String),
    sqlalchemy.Column("score", sqlalchemy.Integer),
    sqlalchemy.Column("player", sqlalchemy.String),
)

engine = sqlalchemy.create_engine(
    os.environ.get("DATABASE_URL"),
    pool_size=3,
    max_overflow=0
)
metadata.create_all(engine)


class Highscore(BaseModel):
    map: str
    score: int
    player: str


class AppNameMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            if request.headers.get('X-App-Name') != 'SnakeQT':
                return Response(status_code=403)
        return await call_next(request)


app = FastAPI()
app.add_middleware(AppNameMiddleware)

maps = []


@app.on_event("startup")
async def startup_event():
    for file in os.listdir("maps"):
        if not file.endswith(".skm"):
            continue
        with zipfile.ZipFile('maps/' + file, 'r') as zip_ref:
            for filename in zip_ref.namelist():
                if not filename == 'map.xml':
                    continue
                with zip_ref.open(filename) as f:
                    tree = ElementTree.parse(f)
                    root_element = tree.getroot()
                    name = root_element.attrib["name"]
                    author = root_element.attrib["author"]
                    maps.append({"id": file, "name": name, "author": author})

    print(f"Maps:\n - " + "\n - ".join([f"{m['name']} by {m['author']} ({m['id']})" for m in maps]))

    await database.connect()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="https://github.com/DenisD3D/SnakeQT")


@app.get("/maps")
async def get_maps():
    return maps


@app.get("/maps/{map_id}")
async def get_map(map_id: str):
    map_file_path = f'maps/{map_id}.skm'
    if os.path.exists(map_file_path):
        return FileResponse(map_file_path, media_type='application/octet-stream', filename=f'{map_id}.skm')
    else:
        return {"error": "Map not found"}


@app.get("/highscores/{map_id}")
async def get_highscore(map_id: str):
    return {el["player"]: el["score"] for el in await database.fetch_all(highscores.select().where(highscores.c.map == map_id).order_by(highscores.c.score))}


@app.get("/highscores/{map_id}/{player}/{score}", include_in_schema=False)
async def set_highscore(map_id: str, player: str, score: int):
    query = highscores.select().where(highscores.c.map == map_id).where(highscores.c.player == player)
    if await database.fetch_one(query):
        if await database.fetch_val(query, highscores.c.score) > score:
            return {"status": "ok"}
        query = highscores.update().where(highscores.c.map == map_id).where(highscores.c.player == player).values(score=score)
    else:
        query = highscores.insert().values(map=map_id, score=score, player=player)
    await database.execute(query)
    return {"status": "ok"}
