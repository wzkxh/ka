def is_prime(n):
  if n < 2:
    return 0
  i = 2
  while i * i <= n:
    if n % i == 0:
      return 0
    i = i + 1
  return 1

def main():
  limit = 1_000_000
  count = 0
  n = 2
  while n < limit:
    if is_prime(n):
      count = count + 1
    n = n + 1
  print(count)

main()
