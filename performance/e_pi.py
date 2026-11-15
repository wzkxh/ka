def compute_e(iterations):
  e = 1.0
  fact = 1.0
  i = 1
  while i < iterations:
    fact = fact * i
    e = e + 1.0 / fact
    i = i + 1
  return e

def compute_pi(iterations):
  pi = 0.0
  sign = 1.0
  i = 0
  while i < iterations:
    term = sign / (2.0 * i + 1.0)
    pi = pi + term
    sign = -sign
    i = i + 1
  return pi * 4.0

def main():
  iterations = 50000000
  e_val = compute_e(20)
  pi_val = compute_pi(iterations)
  print(e_val)  # 2.7182818284590455
  print(pi_val) # 3.1415926335902506

main() # 4.746
