import numpy as np

from face.database import FaceDatabase


database = FaceDatabase()

embedding = np.random.rand(
    512,
).astype("float32")

database.add_face(
    "Aryan",
    embedding,
)

print(database.get_face("Aryan"))

print()

print(database.get_all_faces())

database.close()