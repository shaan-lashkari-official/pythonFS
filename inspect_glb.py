import os
import gltf
from panda3d.core import NodePath

print("=" * 60)
print(f"File size: {os.path.getsize('a320.glb')} bytes")
print("=" * 60)

model_node = gltf.load_model('a320.glb')
model = NodePath(model_node)

print(f"Model loaded: {model}")
print(f"Empty: {model.isEmpty()}")
print(f"Top-level children: {model.getNumChildren()}")
print("=" * 60)
print("SCENE GRAPH:")
model.ls()
print("=" * 60)

bounds = model.getTightBounds()
if bounds:
    mn, mx = bounds
    print(f"Bounds: min={mn}  max={mx}")
    print(f"Size: X={mx.x-mn.x:.2f}  Y={mx.y-mn.y:.2f}  Z={mx.z-mn.z:.2f}")
print("=" * 60)

print("TOP-LEVEL CHILDREN (by name):")
for child in model.getChildren():
    print(f"  {child.getName()!r}")
print("=" * 60)

print("ALL NAMED NODES (for animation matching):")
for np in model.findAllMatches("**/*"):
    n = np.getName()
    if n and n.strip():
        print(f"  {n!r}")