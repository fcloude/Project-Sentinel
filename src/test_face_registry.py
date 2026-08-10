from pathlib import Path
from src.face.face_registry import FaceRegistry
registry = FaceRegistry()
image = Path(__file__).parent.parent / '8454.jpg'
success = registry.register('Aryan', str(image))
print('Registered:', success)
print()
print('Known People:')
for person in registry.list_people():
    print(person)
