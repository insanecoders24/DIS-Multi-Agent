import os
from mangum import Mangum

# Trigger database and path creation manually since lifespan="off" disables startup events
from main import startup, app
startup()

# Setting lifespan="off" can avoid issues with startup events hitting timeout on Lambda cold starts
handler = Mangum(app, lifespan="off")
