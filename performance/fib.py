def fib(n):
  if n < 2:
    return n
  return fib(n-1) + fib(n-2)

def main():
  i = 0
  res = 0
  while i < 36:
    res = fib(i)
    i = i + 1
  print(res)

main()
