# Physics Simulation (Projectile Motion with Air Resistance)

# This simulates an object moving through the air with gravity and
# velocity-dependent drag. It includes a custom Babylonian square root function
# (sqrt) written entirely in primitive float operations, making it an excellent
# test for raw floating-point throughput.

def sqrt(n):
  if n <= 0.0:
    return 0.0
  x = n
  i = 0
  while i < 10:
    x = 0.5 * (x + n / x)
    i = i + 1
  return x

def simulate_projectile():
  x = 0.0
  y = 0.0
  vx = 30.0
  vy = 40.0
  dt = 0.005
  g = 9.81
  k = 0.002

  steps = 0
  while y >= 0.0:
    v = sqrt(vx * vx + vy * vy)
    ax = -k * v * vx
    ay = -g - k * v * vy

    vx = vx + ax * dt
    vy = vy + ay * dt
    x = x + vx * dt
    y = y + vy * dt
    steps = steps + 1
  return steps

def main():
  total_steps = 0
  i = 0
  while i < 3000:
    total_steps = total_steps + simulate_projectile()
    i = i + 1
  print(total_steps) # 4431000 3.192

main()
